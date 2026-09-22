"""Фоновый детект ТИХОГО отвлечения по кадрам экрана.

Анализатор ловит отвлечение по речи. Но если мастер МОЛЧА смотрит видео/соцсети на
экране — речи нет → нет транскрипта → анализатор туда не заглянет. Этот сэмплер
находит «тихие» промежутки (есть запись, картинка меняется = не idle, но речи нет),
смотрит несколько кадров через Pixtral и, если это развлечение, помечает промежуток
событием экрана (screen_events, distraction=true). Отдельно от conversations —
границу анализатора не двигает.

Фазы как в анализаторе: ЧТЕНИЕ+планирование (короткая сессия) → сеть (Pixtral, без
БД) → запись (короткая сессия). Граница = max(ScreenEvent.end_ts) на устройство:
храним событие для КАЖДОГО обработанного промежутка (даже рабочего), чтобы не
пересматривать. Кадры только из неудалённой записи; всё под флагом VISION_SCAN.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import func
from fastapi.concurrency import run_in_threadpool

from . import config, vision, realtime, prompts
from .db import SessionLocal
from .models import Segment, Transcript, ScreenEvent

logger = logging.getLogger("monitoring.vision_sampler")


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _to_ms(dt: datetime) -> int:
    return int(_as_utc(dt).timestamp() * 1000)


def _plan_device(db, device_id: str, now: datetime, lo: datetime,
                 settle: timedelta, gap: timedelta, min_span: timedelta) -> list[dict]:
    """Тихие завершённые промежутки устройства с планом кадров (короткая сессия)."""
    frontier = (
        db.query(func.max(ScreenEvent.end_ts))
        .filter(ScreenEvent.device_id == device_id).scalar()
    )
    start_after = max(lo, _as_utc(frontier)) if frontier else lo
    horizon = now - settle
    if start_after >= horizon:
        return []

    # Только start_ts+duration (не полные ORM-объекты): скан гоняется каждый проход.
    segs = (
        db.query(Segment.start_ts, Segment.duration)
        .filter(Segment.device_id == device_id, Segment.idle.is_(False),
                Segment.start_ts > start_after, Segment.start_ts <= horizon)
        .order_by(Segment.start_ts.asc())
        .limit(3000)
        .all()
    )
    if not segs:
        return []

    trs = (
        db.query(Transcript.start_ts, Transcript.end_ts)
        .filter(Transcript.device_id == device_id,
                Transcript.end_ts >= start_after, Transcript.start_ts <= now)
        .all()
    )
    speech = [(_as_utc(a), _as_utc(b)) for a, b in trs]

    def has_speech(s: datetime, e: datetime) -> bool:
        return any(a < e and b > s for a, b in speech)

    # Тихие сегменты → склеиваем соседние в промежутки (по паузе gap).
    spans: list[list[datetime]] = []
    for sg in segs:
        s = _as_utc(sg.start_ts)
        e = s + timedelta(seconds=(sg.duration or 0))
        if has_speech(s, e):
            continue
        if spans and s - spans[-1][1] <= gap:
            spans[-1][1] = max(spans[-1][1], e)
        else:
            spans.append([s, e])

    out: list[dict] = []
    for s, e in spans:
        if e - s < min_span:
            continue  # слишком короткий — не тратим Pixtral (граница не двинется, ок)
        out.append({
            "start": s, "end": e,
            "frame_plan": vision.plan_frames(db, device_id, _to_ms(s), _to_ms(e), config.VISION_SCAN_SAMPLES),
        })
    return out


def run_once_scan() -> int:
    if not (config.VISION_SCAN and config.VISION and config.MISTRAL_API_KEY):
        return 0
    now = datetime.now(timezone.utc)
    lo = now - timedelta(hours=config.VISION_SCAN_HOURS)
    settle = timedelta(minutes=config.VISION_SCAN_SETTLE_MINUTES)
    gap = timedelta(minutes=config.VISION_SCAN_GAP_MINUTES)
    min_span = timedelta(minutes=config.VISION_SCAN_MIN_MINUTES)

    # --- ЧТЕНИЕ + планирование (короткая сессия), с общим лимитом на проход ---
    plans: list[tuple[str, dict]] = []
    db = SessionLocal()
    try:
        device_ids = [r[0] for r in db.query(Segment.device_id).distinct().all()]
        for device_id in device_ids:
            # Промпт зрения — свой у каждой сети/студии; разрешаем, пока сессия открыта.
            pr = prompts.resolve(db, device_id)
            for sp in _plan_device(db, device_id, now, lo, settle, gap, min_span):
                sp["task"] = pr["vision_task"]
                sp["fmt"] = pr["vision_format"]
                plans.append((device_id, sp))
                if len(plans) >= config.VISION_SCAN_BATCH:
                    break
            if len(plans) >= config.VISION_SCAN_BATCH:
                break
    finally:
        db.close()
    if not plans:
        return 0

    made = 0
    for device_id, sp in plans:
        # --- Сеть (зрение) без удержания соединения с БД ---
        planned = sp["frame_plan"]
        screens = vision.classify_planned(planned, sp.get("task"), sp.get("fmt"))
        # Кадры были, но НИ ОДИН не классифицировался — это сбой зрения (сеть, лимит,
        # недоступная модель), а не «на экране непонятно». Событие НЕ пишем: иначе
        # граница уедет вперёд и промежуток больше никогда не пересмотрят. Повторим
        # на следующем проходе. Пустой frame_plan (запись уже удалена ретеншеном) —
        # другое дело: там смотреть нечего никогда, событие пишем и идём дальше.
        if planned and not screens:
            logger.warning(
                "Зрение не вернуло ни одного кадра для %s (%s..%s): пропускаю промежуток, "
                "граница не двигается. Последняя ошибка: %s",
                device_id, sp["start"], sp["end"], vision.stats.get("last_error"))
            continue
        activity, label, distraction, note = vision.summarize_span(screens)

        # --- Запись (короткая сессия). ---
        db = SessionLocal()
        try:
            db.add(ScreenEvent(
                device_id=device_id, start_ts=sp["start"], end_ts=sp["end"],
                activity=activity, label=label, distraction=distraction, note=note,
            ))
            db.commit()
        finally:
            db.close()
        made += 1
        if distraction:
            realtime.broadcast_soon({"type": "screen", "device_id": device_id})
            logger.info("Тихое отвлечение %s: %s..%s экран=%s",
                        device_id, sp["start"], sp["end"], label or activity)

    return made


async def loop(interval: int | None = None) -> None:
    interval = interval or config.VISION_SCAN_INTERVAL
    while True:
        try:
            n = await run_in_threadpool(run_once_scan)
            if n:
                logger.info("Сэмплер экрана: обработано промежутков %d", n)
        except Exception:  # noqa: BLE001 — фон не должен ронять процесс
            logger.exception("Сэмплер экрана: сбой прохода")
        await asyncio.sleep(interval)
