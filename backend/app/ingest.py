"""Приём сегментов видео от камер (POST /api/upload) + индексация в БД.

Безопасность: Bearer-токен камеры (сравнение в константное время),
защита от path traversal, потоковая запись с ограничением размера.
"""
import os
import re
import json
import math
import shutil
import asyncio
import logging
import secrets
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, UploadFile, File, Form, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from . import config, hls, motion, realtime, transcribe, mistral, vision, access, search as search_index
from .db import get_db, SessionLocal
from .models import Device, Segment, Transcript, Conversation, User
from .security import get_current_user


def _dt_ms(dt: datetime) -> int:
    return int((dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt).timestamp() * 1000)

logger = logging.getLogger("monitoring.ingest")
router = APIRouter(tags=["ingest"])

# Ограничитель одновременных ffmpeg-обработок и держатель фоновых задач.
_INGEST_SEM = asyncio.Semaphore(config.INGEST_CONCURRENCY)
_TRANSCRIBE_SEM = asyncio.Semaphore(config.TRANSCRIBE_CONCURRENCY)
_bg_tasks: set[asyncio.Task] = set()

DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")


def verify_camera_token(authorization: str = Header(None)):
    """Проверка Bearer-токена камеры в константное время."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token format")
    token = authorization[len("Bearer "):].strip()
    if not secrets.compare_digest(token, config.UPLOAD_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized token")


def _safe_device_id(device_id: str) -> str:
    if not DEVICE_ID_RE.match(device_id):
        raise HTTPException(status_code=400, detail="Invalid device_id")
    return device_id


def _safe_filename(filename: str) -> str:
    name = os.path.basename(filename.replace("\\", "/")) if filename else ""
    if not name or name in (".", "..") or not FILENAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid filename")
    return name


def _save_upload(src, dst_path: str, max_bytes: int) -> int:
    """Потоковая запись с контролем размера (в threadpool, не блокирует loop)."""
    size = 0
    try:
        with open(dst_path, "wb") as buffer:
            while True:
                chunk = src.read(config.CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError("File too large")
                buffer.write(chunk)
    except BaseException:
        if os.path.exists(dst_path):
            os.remove(dst_path)
        raise
    return size


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _event_from_filename(name: str) -> str:
    """rec_zoom_2026… → 'zoom'; rec_2026… → 'normal'. Тип — слово между rec_ и датой."""
    parts = name.split("_")
    if len(parts) >= 2 and parts[0] == "rec" and not parts[1].isdigit():
        cleaned = re.sub(r"[^a-z0-9]", "", parts[1].lower())[:32]
        return cleaned or "normal"
    return "normal"


def _parse_start_ts(start_ts: str | None) -> datetime | None:
    """start_ts из формы — epoch в миллисекундах. None, если не прислали/мусор."""
    if start_ts:
        try:
            return datetime.fromtimestamp(int(start_ts) / 1000, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            pass
    return None


# rec_[тип_]ГГГГММДД_ЧЧММСС… — время начала съёмки, его пишет ffmpeg -strftime
_REC_TS_RE = re.compile(r"(\d{8})_(\d{6})")
# Насколько имя файла может опережать «сейчас» (расхождение часов камеры).
_CLOCK_SKEW = timedelta(minutes=10)
# Старше этого имя файла считаем недостоверным (сбитая дата на камере).
_MAX_AGE = timedelta(days=120)
# Расхождение клиентского start_ts с именем файла, о котором стоит сообщить.
_TS_MISMATCH = timedelta(seconds=90)


def _start_from_filename(filename: str, tz_name: str, now: datetime) -> datetime | None:
    """Время начала съёмки из имени файла, переведённое из пояса студии в UTC.

    Это единственный источник, который НЕ зависит от момента отправки: когда
    камера досылает накопленное за дни, только имя файла говорит, когда съёмка
    была на самом деле.
    """
    m = _REC_TS_RE.search(filename)
    if not m or not tz_name:
        return None
    try:
        naive = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
        ts = naive.replace(tzinfo=ZoneInfo(tz_name)).astimezone(timezone.utc)
    except (ValueError, ZoneInfoNotFoundError, KeyError):
        return None
    if ts > now + _CLOCK_SKEW or ts < now - _MAX_AGE:
        return None          # часы камеры врут — доверять нельзя
    return ts


def _resolve_start(filename: str, client_ts: datetime | None, device: Device,
                   now: datetime) -> datetime:
    """Когда сегмент был СНЯТ (а не отправлен).

    Приоритет у имени файла: развёрнутые сейчас клиенты присылают в start_ts
    момент отправки, поэтому при догрузке очереди весь архив съезжал на время
    догрузки (на «Садовой» так уехало на 23 дня). Имя файла от этого не зависит.
    """
    tz_name = device.studio.tz if (device is not None and device.studio) else ""
    by_name = _start_from_filename(filename, tz_name, now)

    if by_name is not None:
        if client_ts is not None and abs(client_ts - by_name) > _TS_MISMATCH:
            # Либо клиент шлёт время отправки, либо у студии неверный пояс.
            logger.warning(
                "%s: start_ts от клиента (%s) расходится с именем файла (%s) на %.0f с — "
                "беру имя файла", device.device_id, client_ts, by_name,
                (client_ts - by_name).total_seconds())
        if now - by_name > timedelta(minutes=10):
            logger.info("%s: догрузка накопленного, файл снят %s (%.1f ч назад)",
                        device.device_id, by_name, (now - by_name).total_seconds() / 3600)
        return by_name

    if client_ts is not None:
        return client_ts
    return now


async def _process_segment(device_id: str, seg_id: int, file_path: str, known_duration: float) -> None:
    """Фоновая обработка: разложить по ракурсам, превью, обновить БД, удалить mp4.

    Вынесено из запроса, чтобы камера получала ответ мгновенно (без ожидания ffmpeg).
    Параллелизм ограничен семафором — не забиваем CPU/пул потоков под наплывом.
    """
    async with _INGEST_SEM:
        try:
            device_hls_dir = os.path.join(config.HLS_DIR, device_id)
            n_views = await run_in_threadpool(hls.probe_video_count, file_path)
            made = await run_in_threadpool(hls.remux_views, file_path, device_hls_dir, seg_id, n_views)

            duration = known_duration
            if duration <= 0:
                duration = await run_in_threadpool(hls.probe_duration, file_path)

            # Анализ по готовому .ts ракурса 0 (тот же артефакт, что и бэкфилл —
            # надёжно читается OpenCV/ffmpeg): простой (нет движения И тихо) +
            # решение о транскрибации (есть ли звук выше порога).
            is_idle = False
            want_transcribe = config.TRANSCRIBE and bool(config.DEEPGRAM_API_KEY)
            if made > 0 and (config.IDLE_DETECTION or want_transcribe):
                probe_path = os.path.join(device_hls_dir, f"seg_{seg_id}_v0.ts")
                frac = None
                if config.IDLE_DETECTION:
                    frac = await run_in_threadpool(motion.max_motion_fraction, probe_path)
                no_motion = frac is not None and frac < config.MOTION_MIN_AREA_FRAC
                # Пик громкости нужен и для idle, и для решения о транскрибации.
                peak = None
                if (config.IDLE_DETECTION and config.IDLE_AUDIO_CHECK) or want_transcribe:
                    peak = await run_in_threadpool(hls.audio_max_db, probe_path)
                # Простой: нет движения И (звук не проверяем ИЛИ тихо).
                if config.IDLE_DETECTION:
                    audio_quiet = (not config.IDLE_AUDIO_CHECK) or peak is None or peak < config.IDLE_AUDIO_SILENCE_DB
                    is_idle = no_motion and audio_quiet
                    if is_idle:
                        logger.info("Сегмент %s (%s): простой (движение %.2f%%, пик аудио %s) → idle",
                                    seg_id, device_id, (frac or 0) * 100,
                                    "n/a" if peak is None else f"{peak:.1f}dB")
                # Транскрибация: если есть звук выше порога — отдельной фоновой задачей.
                if want_transcribe and peak is not None and peak >= config.TRANSCRIBE_MIN_DB:
                    _schedule_transcription(device_id, seg_id)

            if made > 0:
                seg_thumb = os.path.join(device_hls_dir, f"seg_{seg_id}.jpg")
                if await run_in_threadpool(hls.make_thumbnail, file_path, seg_thumb, 320):
                    await run_in_threadpool(
                        shutil.copyfile, seg_thumb, os.path.join(device_hls_dir, "thumb.jpg")
                    )
                await run_in_threadpool(_safe_remove, file_path)  # сырой mp4 больше не нужен
            else:
                logger.warning("HLS-переупаковка не удалась для %s (сегмент %s)", device_id, seg_id)

            # Обновляем метаданные в отдельной сессии (запрос уже завершён).
            db = SessionLocal()
            try:
                seg = db.get(Segment, seg_id)
                if seg is not None:
                    seg.views = n_views
                    seg.idle = is_idle
                    if (seg.duration or 0) <= 0:
                        seg.duration = duration
                dev = db.get(Device, device_id)
                if dev is not None:
                    dev.views = n_views
                db.commit()
            finally:
                db.close()

            # Событие панели — когда виды готовы (плеер точно найдёт .ts).
            realtime.broadcast_soon({"type": "segment", "device_id": device_id})
        except Exception:  # noqa: BLE001 — фон не должен ронять процесс
            logger.exception("Фоновая обработка сегмента %s (%s) упала", seg_id, device_id)


def _schedule_processing(device_id: str, seg_id: int, file_path: str, duration: float) -> None:
    """Запускает фоновую обработку, удерживая ссылку на задачу (иначе GC её съест)."""
    task = asyncio.create_task(_process_segment(device_id, seg_id, file_path, duration))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


async def _transcribe_segment(device_id: str, seg_id: int) -> None:
    """Фоновая транскрибация сегмента (Deepgram) → запись в таблицу transcripts.

    Отдельная задача, чтобы сетевой вызов не тормозил основную обработку/уведомления.
    Транскрипт хранится по абсолютному времени и НЕ удаляется ретеншеном.
    """
    async with _TRANSCRIBE_SEM:
        try:
            hls_dir = os.path.join(config.HLS_DIR, device_id)
            ts_path = os.path.join(hls_dir, f"seg_{seg_id}_v0.ts")
            if not os.path.exists(ts_path):
                ts_path = os.path.join(hls_dir, f"seg_{seg_id}.ts")
            result = await run_in_threadpool(transcribe.transcribe, ts_path)
            if not result or not result.get("text"):
                return
            db = SessionLocal()
            try:
                seg = db.get(Segment, seg_id)
                if seg is None:
                    return
                start_abs = seg.start_ts
                end_abs = start_abs + timedelta(seconds=float(seg.duration or 0))
                db.add(Transcript(
                    device_id=device_id, start_ts=start_abs, end_ts=end_abs,
                    text=result["text"],
                    words=json.dumps(result["words"], ensure_ascii=False),
                ))
                db.commit()
            finally:
                db.close()
            logger.info("Транскрипт сегмента %s (%s): «%s»", seg_id, device_id, result["text"][:80])
            realtime.broadcast_soon({"type": "transcript", "device_id": device_id})
        except Exception:  # noqa: BLE001 — фон не должен ронять процесс
            logger.exception("Транскрибация сегмента %s (%s) упала", seg_id, device_id)


def _schedule_transcription(device_id: str, seg_id: int) -> None:
    task = asyncio.create_task(_transcribe_segment(device_id, seg_id))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


@router.get("/transcribe/status")
def transcribe_status(_: User = Depends(get_current_user)):
    """Здоровье транскрибации для панели: включена ли, счётчики, последняя ошибка."""
    return {
        "enabled": bool(config.DEEPGRAM_API_KEY) and config.TRANSCRIBE,
        "model": config.DEEPGRAM_MODEL,
        **transcribe.stats,
    }


@router.get("/analyze/status")
def analyze_status(_: User = Depends(get_current_user)):
    """Здоровье AI-анализа разговоров (Mistral): включён ли, счётчики, последняя ошибка."""
    return {
        "enabled": bool(config.MISTRAL_API_KEY) and config.ANALYZE,
        "model": config.MISTRAL_MODEL,
        **mistral.stats,
    }


@router.get("/vision/status")
def vision_status(_: User = Depends(get_current_user)):
    """Здоровье зрения по кадрам (Pixtral): включено ли, счётчики, последняя ошибка."""
    return {
        "enabled": bool(config.MISTRAL_API_KEY) and config.VISION,
        "model": config.VISION_MODEL,
        **vision.stats,
    }


@router.get("/search")
def semantic_search(
    q: str = Query(..., min_length=2),
    limit: int = Query(config.SEARCH_LIMIT),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Семантический поиск по разобранным эпизодам (эмбеддинг запроса + косинус)."""
    if not (config.MISTRAL_API_KEY and config.EMBED):
        return {"results": []}
    qvec = mistral.embed_one(q.strip())
    if not qvec:
        return {"results": []}

    # Косинус по кэшу распарсенных эмбеддингов (см. search.py).
    # Берём с запасом и отсеиваем чужие камеры: ранжирование идёт по всей базе,
    # поэтому фильтровать надо ПОСЛЕ него, иначе выдача просядет по релевантности.
    allowed = access.allowed_device_ids(db, user)
    ranked = search_index.search(db, qvec, max(1, limit) if allowed is None else max(1, limit) * 5)
    if allowed is not None:
        ranked = [(sim, m) for sim, m in ranked if m["device_id"] in allowed][:max(1, limit)]
    names = {d.device_id: (d.friendly_name or d.device_id)
             for d in access.visible_devices(db, user)}

    results = []
    for sim, m in ranked:
        results.append({
            "id": m["id"],
            "device_id": m["device_id"],
            "device_name": names.get(m["device_id"], m["device_id"]),
            "start": _dt_ms(m["start_ts"]),
            "end": _dt_ms(m["end_ts"]),
            "type": m["kind"] or "other",
            "title": m["title"],
            "score": m["score"],
            "similarity": round(float(sim), 3),
            "summary": m["summary"],
        })
    return {"results": results}


@router.get("/objections")
def objections(
    limit: int = Query(200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Библиотека возражений/жалоб/пропущенных противопоказаний по всем разговорам."""
    kinds = {"objection", "contra", "complaint", "redflag"}
    names = {d.device_id: (d.friendly_name or d.device_id)
             for d in access.visible_devices(db, user)}
    allowed = access.allowed_device_ids(db, user)
    q = (
        db.query(Conversation)
        .filter(Conversation.highlights != "", Conversation.highlights != "[]")
    )
    if allowed is not None:
        if not allowed:
            return {"items": []}
        q = q.filter(Conversation.device_id.in_(allowed))
    rows = q.order_by(Conversation.start_ts.desc()).limit(3000).all()
    items = []
    for r in rows:
        try:
            hl = json.loads(r.highlights)
        except (ValueError, TypeError):
            continue
        for h in hl:
            if h.get("kind") in kinds and h.get("text"):
                try:
                    t = int(h["t"])
                except (KeyError, ValueError, TypeError):
                    continue
                items.append({
                    "device_id": r.device_id,
                    "device_name": names.get(r.device_id, r.device_id),
                    "t": t,
                    "text": str(h["text"]),
                    "kind": h["kind"],
                    "conv_type": r.kind or "other",
                    "score": r.score,
                })
        if len(items) >= limit * 3:
            break
    items.sort(key=lambda x: x["t"], reverse=True)
    return {"items": items[:limit]}


@router.post("/upload", dependencies=[Depends(verify_camera_token)])
async def upload_chunk(
    file: UploadFile = File(...),
    device_id: str = Form(...),
    device_host: str = Form(""),
    device_user: str = Form(""),
    start_ts: str = Form(None),     # epoch ms начала сегмента (рекомендуется слать)
    duration: float = Form(0.0),    # длительность сегмента, сек (рекомендуется слать)
    event: str = Form(""),          # тип записи; если пусто — берём из имени файла
    db: Session = Depends(get_db),
):
    device_id = _safe_device_id(device_id)
    filename = _safe_filename(file.filename)
    seg_event = re.sub(r"[^a-z0-9]", "", event.lower())[:32] or _event_from_filename(filename)

    device_dir = os.path.join(config.UPLOAD_DIR, device_id)
    os.makedirs(device_dir, exist_ok=True)
    file_path = os.path.join(device_dir, filename)

    # Защита «в глубину»: путь обязан оставаться внутри каталога устройства.
    if os.path.commonpath([os.path.realpath(file_path), os.path.realpath(device_dir)]) != os.path.realpath(device_dir):
        raise HTTPException(status_code=400, detail="Invalid path")

    try:
        size = await run_in_threadpool(_save_upload, file.file, file_path, config.MAX_FILE_SIZE)
    except ValueError:
        raise HTTPException(status_code=413, detail="File too large")
    except Exception:
        logger.exception("Ошибка записи файла от устройства %s", device_id)
        return JSONResponse(status_code=500, content={"status": "error", "message": "Internal error"})

    now = datetime.now(timezone.utc)
    seg_duration = float(duration or 0.0)  # если 0 — уточним в фоне через ffprobe

    # Upsert устройства. Нужен ДО определения времени съёмки: часовой пояс
    # лежит на студии устройства, без него имя файла не перевести в UTC.
    device = db.get(Device, device_id)
    if device is None:
        device = Device(device_id=device_id, friendly_name=device_id)
        db.add(device)
    device.host = device_host or device.host
    device.user = device_user or device.user
    device.last_file = filename
    # last_seen — именно момент связи с камерой, а не время съёмки: по нему
    # считается «онлайн», и догрузка старого архива не должна его сдвигать.
    device.last_seen = now

    seg_start = _resolve_start(filename, _parse_start_ts(start_ts), device, now)

    # Индексируем сегмент и сразу коммитим — получаем стабильный id.
    rel_path = os.path.relpath(file_path, config.STORAGE_DIR)
    segment = Segment(
        device_id=device_id,
        path=rel_path,
        start_ts=seg_start,
        duration=seg_duration,
        size=size,
        event=seg_event,
    )
    db.add(segment)
    db.commit()
    db.refresh(segment)

    # Тяжёлый ffmpeg (разбор по ракурсам, превью) — в фон. Камера получает ответ сразу.
    _schedule_processing(device_id, segment.id, file_path, seg_duration)

    return {"status": "success", "message": f"File {filename} uploaded successfully", "size": size}
