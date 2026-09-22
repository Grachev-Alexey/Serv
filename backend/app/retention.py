"""Очистка архива по сроку хранения (RETENTION_DAYS).

Раз в час удаляет сегменты старше срока: файлы (.ts/.jpg, сырой .mp4 если остался)
и соответствующие записи в БД. Порциями, чтобы не держать всё в памяти.
"""
import os
import glob
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import or_, and_
from fastapi.concurrency import run_in_threadpool

from . import config
from .db import SessionLocal
from .models import Segment

logger = logging.getLogger("monitoring.retention")

_BATCH = 2000


def _remove(path: str | None) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def run_once() -> int:
    """Удаляет одну порцию просроченных сегментов. Возвращает число удалённых.

    Два срока: активные сегменты живут RETENTION_DAYS дней, а «простой» (idle,
    ничего не менялось) — всего IDLE_RETENTION_HOURS часов, чтобы не копить пустое.
    """
    now = datetime.now(timezone.utc)
    conds = []
    if config.RETENTION_DAYS > 0:
        conds.append(Segment.start_ts < now - timedelta(days=config.RETENTION_DAYS))
    if config.IDLE_RETENTION_HOURS > 0:
        conds.append(and_(Segment.idle.is_(True),
                          Segment.start_ts < now - timedelta(hours=config.IDLE_RETENTION_HOURS)))
    if not conds:
        return 0
    db = SessionLocal()
    removed = 0
    try:
        old = (
            db.query(Segment)
            .filter(or_(*conds))
            .order_by(Segment.start_ts.asc())
            .limit(_BATCH)
            .all()
        )
        for s in old:
            hls_dir = os.path.join(config.HLS_DIR, s.device_id)
            for p in glob.glob(os.path.join(hls_dir, f"seg_{s.id}_v*.ts")):
                _remove(p)                                   # виды по ракурсам
            _remove(os.path.join(hls_dir, f"seg_{s.id}.ts"))  # старый муксовый (если был)
            _remove(os.path.join(hls_dir, f"seg_{s.id}.jpg"))
            if s.path:
                _remove(os.path.join(config.STORAGE_DIR, s.path))
            db.delete(s)
            removed += 1
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Retention: ошибка при очистке")
    finally:
        db.close()
    return removed


async def loop(interval_seconds: int = 3600) -> None:
    """Фоновая петля: раз в час вычищаем всё просроченное (порциями до конца)."""
    while True:
        try:
            total = 0
            while True:
                n = await run_in_threadpool(run_once)
                total += n
                if n < _BATCH:
                    break
            if total:
                logger.info("Retention: удалено %d сегментов старше %d дн.", total, config.RETENTION_DAYS)
        except Exception:
            logger.exception("Retention: сбой цикла")
        await asyncio.sleep(interval_seconds)
