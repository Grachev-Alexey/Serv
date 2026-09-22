"""Зрение по кадрам экрана (Pixtral / Mistral multimodal).

Извлекает несколько кадров из записи рабочего дня и классифицирует, что открыто
на экране (рабочая CRM/расписание vs видео/соцсети/мессенджер) — усиливает детект
отвлечения. Результат отдаётся анализатору как подсказка к тексту и прикрепляется
к эпизодам меткой экрана.

Синхронно (ffmpeg + httpx), вызывается из фоновой задачи анализатора в threadpool.
Кадры берём напрямую из .ts нужного момента; если запись уже удалена ретеншеном —
просто пропускаем (расходов на старый архив нет). Любой сбой зрения не мешает
анализу текста: наверх возвращается пустой список.
"""
import os
import time
import base64
import json
import logging
import subprocess
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

import httpx

from . import config, prompts
from .models import Segment

logger = logging.getLogger("monitoring.vision")

CHAT_URL = "https://api.mistral.ai/v1/chat/completions"

_ACTIVITIES = {"work", "communication", "entertainment", "idle", "unknown"}


# Статистика (в памяти) — для /api/vision/status и индикатора в панели.
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
    logger.warning("Vision: %s", msg)


def _from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _to_ms(dt: datetime) -> int:
    d = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return int(d.timestamp() * 1000)


def _view_file(device_id: str, seg_id: int) -> str | None:
    """Файл .ts (ракурс 0) для сегмента, если он ещё на диске."""
    hls_dir = os.path.join(config.HLS_DIR, device_id)
    for name in (f"seg_{seg_id}_v0.ts", f"seg_{seg_id}.ts"):
        if os.path.exists(os.path.join(hls_dir, name)):
            return name
    return None


def _ts_file_at(db, device_id: str, ts_ms: int):
    """(.ts путь, смещение в секундах) для момента ts_ms — или (None, 0)."""
    dt = _from_ms(ts_ms)
    seg = (
        db.query(Segment)
        .filter(Segment.device_id == device_id, Segment.start_ts <= dt)
        .order_by(Segment.start_ts.desc())
        .first()
    )
    if seg is None:
        seg = (
            db.query(Segment)
            .filter(Segment.device_id == device_id, Segment.start_ts >= dt)
            .order_by(Segment.start_ts.asc())
            .first()
        )
    if seg is None:
        return None, 0.0
    name = _view_file(device_id, seg.id)
    if not name:
        return None, 0.0
    path = os.path.join(config.HLS_DIR, device_id, name)
    dur = float(seg.duration or 0)
    offset = (ts_ms - _to_ms(seg.start_ts)) / 1000.0
    offset = max(0.0, min(offset, max(0.0, dur - 0.2)))
    return path, offset


def _extract_jpeg(path: str, offset: float) -> bytes | None:
    """Один кадр из .ts в момент offset (сек) → JPEG-байты (ужат по ширине)."""
    try:
        r = subprocess.run(
            [config.FFMPEG_BIN, "-hide_banner", "-loglevel", "error",
             "-ss", f"{offset:.2f}", "-i", path, "-frames:v", "1",
             "-vf", f"scale={config.VISION_MAX_WIDTH}:-2",
             "-q:v", "5", "-f", "image2", "pipe:1"],
            capture_output=True, timeout=30,
        )
        if r.returncode == 0 and r.stdout:
            return r.stdout
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def classify_frame(jpeg: bytes, task: str | None = None,
                   fmt: str | None = None) -> dict | None:
    """Классифицируем один кадр через Pixtral → {activity,label,distraction,note} или None."""
    if not config.MISTRAL_API_KEY:
        return None
    stats["attempts"] += 1
    data_uri = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
    payload = {
        "model": config.VISION_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text",
                 "text": (task or prompts.DEFAULTS["vision_task"]) + "\n"
                         + (fmt or prompts.DEFAULTS["vision_format"])},
                {"type": "image_url", "image_url": data_uri},
            ],
        }],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {config.MISTRAL_API_KEY}",
        "Content-Type": "application/json",
    }

    last_err = "неизвестная ошибка"
    for attempt in range(config.VISION_RETRIES + 1):
        transient = False
        try:
            resp = httpx.post(CHAT_URL, json=payload, headers=headers, timeout=config.VISION_TIMEOUT)
        except httpx.RequestError as e:
            last_err, transient = f"сеть/таймаут: {type(e).__name__}", True
        else:
            if resp.status_code == 200:
                try:
                    content = resp.json()["choices"][0]["message"]["content"]
                    parsed = json.loads(content)
                except (KeyError, IndexError, TypeError, ValueError):
                    _record_failure("неожиданный формат ответа Pixtral")
                    return None
                _record_ok()
                return _norm(parsed)
            elif resp.status_code == 429 or resp.status_code >= 500:
                last_err, transient = f"HTTP {resp.status_code}", True
            else:
                _record_failure(f"HTTP {resp.status_code}: {resp.text[:120]}")
                return None

        if transient and attempt < config.VISION_RETRIES:
            stats["retries"] += 1
            time.sleep(config.VISION_RETRY_BACKOFF * (2 ** attempt))

    _record_failure(f"{last_err} (после {config.VISION_RETRIES} повторов)")
    return None


def _norm(p: dict) -> dict:
    """Приводим ответ модели к безопасному виду."""
    if not isinstance(p, dict):
        return {"activity": "unknown", "label": "", "distraction": False, "note": ""}
    activity = p.get("activity") if p.get("activity") in _ACTIVITIES else "unknown"
    return {
        "activity": activity,
        "label": str(p.get("label", "")).strip()[:60],
        "distraction": bool(p.get("distraction")) or activity == "entertainment",
        "note": str(p.get("note", "")).strip()[:200],
    }


def plan_frames(db, device_id: str, lo_ms: int, hi_ms: int, n: int) -> list[tuple[int, str, float]]:
    """Планируем n равномерных кадров в [lo,hi] → [(t, .ts-путь, смещение_сек)].

    Только обращение к БД (быстро) — чтобы вызывающий мог ЗАКРЫТЬ соединение перед
    тяжёлыми ffmpeg+Pixtral. Моменты без записи (удалена/нет файла) отсеиваем.
    """
    if not (config.VISION and config.MISTRAL_API_KEY) or hi_ms <= lo_ms or n <= 0:
        return []
    span = hi_ms - lo_ms
    times = [lo_ms + int(span * (i + 0.5) / n) for i in range(n)]
    out: list[tuple[int, str, float]] = []
    try:
        for t in times:
            path, offset = _ts_file_at(db, device_id, t)
            if path:
                out.append((t, path, offset))
    except Exception:  # noqa: BLE001 — планирование не должно ронять анализ
        logger.exception("Vision: сбой планирования кадров")
        return []
    return out


def classify_planned(frames: list[tuple[int, str, float]], task: str | None = None,
                     fmt: str | None = None) -> list[dict]:
    """По плану кадров: извлекаем JPEG (ffmpeg, последовательно) и классифицируем
    параллельно (до VISION_CONCURRENCY). БЕЗ обращения к БД. → [{t,activity,...}]."""
    if not frames:
        return []
    extracted: list[tuple[int, bytes]] = []
    for t, path, offset in frames:
        jpeg = _extract_jpeg(path, offset)
        if jpeg:
            extracted.append((t, jpeg))
    if not extracted:
        return []

    out: list[dict] = []
    try:
        workers = max(1, min(config.VISION_CONCURRENCY, len(extracted)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(lambda f: (f[0], classify_frame(f[1], task, fmt)), extracted))
        for t, res in results:
            if res:
                out.append({"t": t, **res})
    except Exception:  # noqa: BLE001
        logger.exception("Vision: сбой классификации кадров")
        return []

    out.sort(key=lambda s: s["t"])
    return out


def sample_screens(db, device_id: str, lo_ms: int, hi_ms: int, n: int,
                   task: str | None = None, fmt: str | None = None) -> list[dict]:
    """Удобная обёртка: план + классификация за один вызов (держит db всё время)."""
    return classify_planned(plan_frames(db, device_id, lo_ms, hi_ms, n), task, fmt)


_HHMM = "%H:%M"


def _hhmm(ms: int) -> str:
    # Локального времени сервера достаточно для подсказки LLM (порядок/близость).
    return datetime.fromtimestamp(ms / 1000).strftime(_HHMM)


_ACT_RU = {
    "work": "работа", "communication": "общение",
    "entertainment": "развлечение", "idle": "простой", "unknown": "неясно",
}


def build_hint(samples: list[dict], header: str | None = None) -> str:
    """Компактная «экранная лента» для промпта анализатора."""
    if not samples:
        return ""
    rows = "\n".join(
        f"- {_hhmm(s['t'])} {_ACT_RU.get(s['activity'], s['activity'])}: {s['label'] or s.get('note', '')}"
        for s in samples
    )
    return (header or prompts.DEFAULTS["screen_hint_header"]) + "\n" + rows


def dominant_label(samples: list[dict]) -> str:
    """Преобладающая метка экрана среди сэмплов эпизода (для чипа в карточке)."""
    if not samples:
        return ""
    counts: dict[str, int] = {}
    for s in samples:
        key = s.get("label") or _ACT_RU.get(s.get("activity", ""), "")
        if key:
            counts[key] = counts.get(key, 0) + 1
    if not counts:
        return ""
    return max(counts.items(), key=lambda kv: kv[1])[0]


def summarize_span(samples: list[dict]) -> tuple[str, str, bool, str]:
    """Свод по кадрам промежутка → (activity, label, distraction, note).

    distraction — если половина и более кадров развлечение/личное. Пустой ввод
    (кадры не извлеклись, напр. видео удалено) → неопределённо, не отвлечение."""
    if not samples:
        return "unknown", "", False, ""
    acts: dict[str, int] = {}
    for s in samples:
        acts[s.get("activity", "unknown")] = acts.get(s.get("activity", "unknown"), 0) + 1
    activity = max(acts.items(), key=lambda kv: kv[1])[0]
    label = dominant_label(samples)
    distraction = sum(1 for s in samples if s.get("distraction")) * 2 >= len(samples)
    note = next((s.get("note", "") for s in samples if s.get("note")), "")
    return activity, label, bool(distraction), note[:255]
