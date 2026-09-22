import time
import json
import logging
from datetime import datetime, timezone

import httpx

from . import config, prompts

logger = logging.getLogger("monitoring.mistral")

CHAT_URL = "https://api.mistral.ai/v1/chat/completions"
EMBED_URL = "https://api.mistral.ai/v1/embeddings"

SYSTEM_PROMPT = (
    "Ты — ассистент контроля качества салона лазерной эпиляции. На вход — транскрипт разговора "
    "сотрудника с клиентом (каждая строка: таймкод в миллисекундах, TAB, текст реплики). "
    "Сделай краткую деловую сводку и выдели ключевые моменты. Отвечай ТОЛЬКО валидным JSON "
    "на русском, без пояснений."
)

stats: dict = {
    "attempts": 0, "ok": 0, "failed": 0, "retries": 0,
    "last_ok_at": None, "last_error": None, "last_error_at": None,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_ok() -> None:
    stats["ok"] += 1
    stats["last_ok_at"] = _now_iso()


def _record_failure(msg: str) -> None:
    stats["failed"] += 1
    stats["last_error"] = msg
    stats["last_error_at"] = _now_iso()
    logger.warning("Mistral: %s", msg)


def _chat(messages: list[dict]) -> str | None:
    if not config.MISTRAL_API_KEY:
        return None
    stats["attempts"] += 1
    payload = {
        "model": config.MISTRAL_MODEL,
        "messages": messages,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {config.MISTRAL_API_KEY}",
        "Content-Type": "application/json",
    }

    last_err = "неизвестная ошибка"
    for attempt in range(config.MISTRAL_RETRIES + 1):
        transient = False
        try:
            resp = httpx.post(CHAT_URL, json=payload, headers=headers, timeout=config.MISTRAL_TIMEOUT)
        except httpx.RequestError as e:
            last_err, transient = f"сеть/таймаут: {type(e).__name__}", True
        else:
            if resp.status_code == 200:
                try:
                    content = resp.json()["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError, ValueError):
                    _record_failure("неожиданный формат ответа Mistral")
                    return None
                _record_ok()
                return content
            elif resp.status_code == 429 or resp.status_code >= 500:
                last_err, transient = f"HTTP {resp.status_code}", True
            else:
                _record_failure(f"HTTP {resp.status_code}: {resp.text[:120]}")
                return None

        if transient and attempt < config.MISTRAL_RETRIES:
            stats["retries"] += 1
            time.sleep(config.MISTRAL_RETRY_BACKOFF * (2 ** attempt))

    _record_failure(f"{last_err} (после {config.MISTRAL_RETRIES} повторов)")
    return None


_TYPES = {"consultation", "sale", "distraction", "internal", "other"}
_HL_KINDS = {"objection", "upsell", "contra", "promise", "complaint", "redflag", "other"}
_ROLES = {"master", "seller", "client", "other"}
_SENTIMENTS = {"happy", "neutral", "hesitant", "unhappy"}


def _clampi(v, lo, hi, default=None):
    try:
        return max(lo, min(int(v), hi))
    except (ValueError, TypeError):
        return default


def _norm_episode(ep: dict, lo_ms: int, hi_ms: int,
                  crit_keys: tuple[str, ...] = ()) -> dict | None:
    if not isinstance(ep, dict):
        return None
    start = _clampi(ep.get("start_ms"), lo_ms, hi_ms, lo_ms)
    end = _clampi(ep.get("end_ms"), lo_ms, hi_ms, hi_ms)
    if end < start:
        start, end = end, start
    kind = ep.get("type") if ep.get("type") in _TYPES else "other"

    participants = []
    for p in ep.get("participants", []) or []:
        if isinstance(p, dict):
            role = p.get("role") if p.get("role") in _ROLES else "other"
            participants.append({"role": role, "note": str(p.get("note", "")).strip()[:120]})

    criteria = {}
    raw_crit = ep.get("criteria") or {}
    if isinstance(raw_crit, dict):
        for key in crit_keys:
            if key in raw_crit:
                c = _clampi(raw_crit[key], 0, 10)
                if c is not None:
                    criteria[key] = c

    highlights = []
    for h in ep.get("highlights", []) or []:
        if not isinstance(h, dict):
            continue
        t = _clampi(h.get("t"), lo_ms, hi_ms)
        text = str(h.get("text", "")).strip()
        if t is None or not text:
            continue
        hk = h.get("kind") if h.get("kind") in _HL_KINDS else "other"
        highlights.append({"t": t, "text": text[:300], "kind": hk})

    clean = []
    for c in ep.get("clean", []) or []:
        if not isinstance(c, dict):
            continue
        t = _clampi(c.get("t"), lo_ms, hi_ms, start)
        text = str(c.get("text", "")).strip()
        if not text:
            continue
        clean.append({"speaker": str(c.get("speaker", "")).strip()[:24], "t": t, "text": text[:600]})

    flags = [str(f).strip()[:160] for f in (ep.get("flags") or []) if str(f).strip()]

    sentiment = ep.get("sentiment") if ep.get("sentiment") in _SENTIMENTS else None

    return {
        "start_ms": start, "end_ms": end, "type": kind,
        "title": str(ep.get("title", "")).strip()[:120],
        "participants": participants,
        "summary": str(ep.get("summary", "")).strip(),
        "score": _clampi(ep.get("score"), 0, 100),
        "criteria": criteria,
        "seller_score": _clampi(ep.get("seller_score"), 0, 100),
        "sentiment": sentiment,
        "flags": flags[:10],
        "highlights": highlights[:10],
        "clean": clean,
    }


def embed(texts: list[str]) -> list[list[float]] | None:
    if not config.MISTRAL_API_KEY or not texts:
        return None
    payload = {"model": config.MISTRAL_EMBED_MODEL, "input": texts}
    headers = {"Authorization": f"Bearer {config.MISTRAL_API_KEY}", "Content-Type": "application/json"}
    last_err = "неизвестная ошибка"
    for attempt in range(config.MISTRAL_RETRIES + 1):
        transient = False
        try:
            resp = httpx.post(EMBED_URL, json=payload, headers=headers, timeout=config.MISTRAL_TIMEOUT)
        except httpx.RequestError as e:
            last_err, transient = f"сеть/таймаут: {type(e).__name__}", True
        else:
            if resp.status_code == 200:
                try:
                    return [d["embedding"] for d in resp.json()["data"]]
                except (KeyError, IndexError, TypeError, ValueError):
                    _record_failure("неожиданный формат ответа embeddings")
                    return None
            elif resp.status_code == 429 or resp.status_code >= 500:
                last_err, transient = f"HTTP {resp.status_code}", True
            else:
                _record_failure(f"embeddings HTTP {resp.status_code}")
                return None
        if transient and attempt < config.MISTRAL_RETRIES:
            stats["retries"] += 1
            time.sleep(config.MISTRAL_RETRY_BACKOFF * (2 ** attempt))
    _record_failure(f"embeddings: {last_err}")
    return None


def embed_one(text: str) -> list[float] | None:
    r = embed([text])
    return r[0] if r else None


def analyze_block(lines: list[dict], lo_ms: int, hi_ms: int, screen_hint: str = "",
                  pr: dict | None = None) -> list[dict] | None:
    """pr — промпты, разрешённые под конкретную камеру (см. prompts.resolve)."""
    if not config.MISTRAL_API_KEY or not lines:
        return None
    pr = pr or dict(prompts.DEFAULTS)
    body = "\n".join(f"{l['ms']}\t{l['text']}" for l in lines)
    crit = "\n".join(f"- {k}: {label}" for k, label in prompts.criteria_list(pr["criteria"]))
    screen_block = ("\n\n" + screen_hint + "\n") if screen_hint else ""
    user = (
        pr["analyzer_intro"] + "\n\n" + body + screen_block + "\n"
        + pr["analyzer_task"] + "\n"
        + f"Критерии:\n{crit}\n\n"
        + pr["analyzer_format"]
    )
    content = _chat([
        {"role": "system", "content": pr["analyzer_system"]},
        {"role": "user", "content": user},
    ])
    if not content:
        return None
    try:
        data = json.loads(content)
        raw = data.get("episodes", []) if isinstance(data, dict) else []
    except (ValueError, TypeError):
        _record_failure("ответ Mistral не распарсился как JSON")
        return None

    ck = tuple(k for k, _ in prompts.criteria_list(pr["criteria"]))
    episodes = [e for e in (_norm_episode(ep, lo_ms, hi_ms, ck) for ep in raw) if e]
    episodes.sort(key=lambda e: e["start_ms"])
    return episodes
