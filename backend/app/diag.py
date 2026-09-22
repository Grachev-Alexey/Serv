"""Пассивная диагностика зависаний.

Раз в N секунд пишем в лог загрузку пула рабочих потоков, пула соединений БД,
число задач event loop и задержку самого loop. Когда что-то упрётся в потолок
(threadpool=X/X надолго, db_pool checked out растёт и не падает, loop_lag скачет
до секунд) — это будет видно прямо в `docker compose logs backend`, без ptrace
и без снятия дампов. По этому следу находим настоящую причину, а не гадаем.

Если логи DIAG во время зависания ВНЕЗАПНО прекращаются — значит заблокирован
сам event loop (синхронный вызов на нём). Если продолжают идти, но threadpool
забит под завязку — упёрлись в пул потоков (sync-эндпоинты голодают).
"""
import os
import time
import asyncio
import logging
import threading

from .db import engine

logger = logging.getLogger("monitoring.diag")


def _threadpool_stats() -> tuple[int, int]:
    """Занятые/всего токенов пула потоков anyio (в нём крутятся sync-эндпоинты)."""
    try:
        import anyio
        lim = anyio.to_thread.current_default_thread_limiter()
        return lim.borrowed_tokens, lim.total_tokens
    except Exception:  # noqa: BLE001
        return -1, -1


def _db_checkedout() -> int:
    """Сколько соединений БД сейчас занято (checked out из пула)."""
    try:
        return engine.pool.checkedout()
    except Exception:  # noqa: BLE001
        return -1


async def loop(interval: int = 30) -> None:
    logger.info("DIAG старт: pid=%d, интервал=%d c (пишу только под нагрузкой)", os.getpid(), interval)
    while True:
        t0 = time.monotonic()
        await asyncio.sleep(interval)
        lag = time.monotonic() - t0 - interval          # насколько loop проспал дольше положенного
        borrowed, total = _threadpool_stats()
        checked_out = _db_checkedout()
        try:
            tasks = len(asyncio.all_tasks())
        except Exception:  # noqa: BLE001
            tasks = -1
        # В простое молчим (чтобы не засорять лог); пишем, только когда есть нагрузка
        # или подозрительная задержка loop — то, что нужно для диагностики зависаний.
        if borrowed > 0 or checked_out > 0 or lag > 0.2:
            logger.info(
                "DIAG threads=%d loop_tasks=%d loop_lag=%.2fs threadpool=%d/%d db_checkedout=%d",
                threading.active_count(), tasks, lag, borrowed, total, checked_out,
            )
