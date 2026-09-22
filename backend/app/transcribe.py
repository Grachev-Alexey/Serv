"""Транскрибация речи сегмента через Deepgram.

Достаём аудио из .ts, поднимаем/выравниваем громкость (тихую речь — вверх),
шлём в Deepgram (pre-recorded API) и возвращаем текст + пословные таймкоды.
Всё синхронно (subprocess + httpx) — вызывается из фоновой задачи в threadpool.
"""
import time
import logging
import subprocess
from datetime import datetime, timezone

import httpx

from . import config

logger = logging.getLogger("monitoring.transcribe")

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"

# Статистика распознавания (в памяти; сбрасывается при рестарте). Отдаётся эндпоинтом
# /api/transcribe/status и показывается индикатором в панели — чтобы не лезть в логи.
stats: dict = {
    "attempts": 0,     # попыток (сегментов)
    "ok": 0,           # успешных
    "failed": 0,       # неуспешных (после всех ретраев)
    "retries": 0,      # сколько раз повторяли
    "last_ok_at": None,
    "last_error": None,
    "last_error_at": None,
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
    logger.warning("Deepgram: %s", msg)


def _extract_audio(ts_path: str) -> bytes | None:
    """Аудио из .ts → mono 16 kHz WAV в память, с нормализацией громкости.

    16 kHz mono — то, что нужно распознавалке; loudnorm вытягивает тихую речь.
    """
    cmd = [config.FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-i", ts_path,
           "-map", "0:a:0", "-vn"]
    if config.TRANSCRIBE_AUDIO_FILTER:
        cmd += ["-af", config.TRANSCRIBE_AUDIO_FILTER]
    cmd += ["-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=60)
        if r.returncode == 0 and r.stdout:
            return r.stdout
    except (OSError, subprocess.SubprocessError):
        logger.warning("Не удалось извлечь аудио из %s", ts_path, exc_info=True)
    return None


def transcribe(ts_path: str) -> dict | None:
    """Расшифровать сегмент. → {"text": str, "words": [{"w","s","e"}]} или None.

    s/e — секунды от начала сегмента. None, если нет ключа/аудио/ошибка/пусто.
    Транзиентные ошибки (сеть, таймаут, 429, 5xx) повторяются с экспоненциальным
    бэкоффом; постоянные (401/400/…) — сразу фиксируются как ошибка без повторов.
    """
    if not config.DEEPGRAM_API_KEY:
        return None
    audio = _extract_audio(ts_path)
    if not audio:
        _record_failure("не удалось извлечь аудио сегмента")
        return None

    stats["attempts"] += 1
    params = {
        "model": config.DEEPGRAM_MODEL,
        "language": config.DEEPGRAM_LANGUAGE,
        "punctuate": "true",
        "smart_format": "true",
    }
    headers = {
        "Authorization": f"Token {config.DEEPGRAM_API_KEY}",
        "Content-Type": "audio/wav",
    }

    last_err = "неизвестная ошибка"
    for attempt in range(config.DEEPGRAM_RETRIES + 1):
        transient = False
        try:
            resp = httpx.post(DEEPGRAM_URL, params=params, headers=headers,
                              content=audio, timeout=config.DEEPGRAM_TIMEOUT)
        except httpx.RequestError as e:
            last_err, transient = f"сеть/таймаут: {type(e).__name__}", True
        else:
            if resp.status_code == 200:
                try:
                    alt = resp.json()["results"]["channels"][0]["alternatives"][0]
                except (KeyError, IndexError, TypeError, ValueError):
                    _record_failure("неожиданный формат ответа Deepgram")
                    return None
                text = (alt.get("transcript") or "").strip()
                words = [
                    {"w": w.get("word", ""), "s": round(float(w.get("start", 0)), 2),
                     "e": round(float(w.get("end", 0)), 2)}
                    for w in alt.get("words", [])
                ]
                _record_ok()
                return {"text": text, "words": words}
            elif resp.status_code == 429 or resp.status_code >= 500:
                last_err, transient = f"HTTP {resp.status_code}", True   # повторяемая
            else:
                # 4xx (401 — неверный ключ, 400 — плохой запрос) — повторять бессмысленно.
                _record_failure(f"HTTP {resp.status_code}: {resp.text[:120]}")
                return None

        if transient and attempt < config.DEEPGRAM_RETRIES:
            stats["retries"] += 1
            time.sleep(config.DEEPGRAM_RETRY_BACKOFF * (2 ** attempt))

    _record_failure(f"{last_err} (после {config.DEEPGRAM_RETRIES} повторов)")
    return None
