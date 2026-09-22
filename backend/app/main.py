"""Точка входа FastAPI-приложения панели мониторинга."""
import signal
import asyncio
import logging
import secrets
import faulthandler

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config, retention, diag, analyzer, vision_sampler
from .db import SessionLocal, init_db
from .models import User
from .security import hash_password
from .auth import router as auth_router
from .admin import router as admin_router
from .prompts_api import router as prompts_router
from .devices import router as devices_router
from .ingest import router as ingest_router
from .streaming import router as streaming_router
from .realtime import router as realtime_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("monitoring")

# Диагностика зависаний без перезапуска: `kill -USR1 1` внутри контейнера
# вывалит стек ВСЕХ потоков в stderr → виден в `docker compose logs backend`.
# Так мы точно увидим, где процесс застрял, вместо гадания.
faulthandler.enable()
if hasattr(signal, "SIGUSR1"):
    faulthandler.register(signal.SIGUSR1, all_threads=True)


def _seed_admin() -> None:
    """Создаём администратора при первом запуске (пароль из ENV или сгенерированный)."""
    db = SessionLocal()
    try:
        # Создаём именно заданного в .env админа, если его ещё нет
        # (позволяет добавить новую учётку, не пересоздавая базу).
        if db.query(User).filter(User.username == config.ADMIN_USER).first():
            return
        password = config.ADMIN_PASSWORD
        if not password:
            password = secrets.token_urlsafe(12)
            logger.warning(
                "ADMIN_PASSWORD не задан. Создан администратор '%s' с паролем: %s",
                config.ADMIN_USER, password,
            )
        db.add(User(username=config.ADMIN_USER, password_hash=hash_password(password),
                    is_admin=True))
        db.commit()
        logger.info("Администратор '%s' создан.", config.ADMIN_USER)
    finally:
        db.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Monitoring Server API")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.ALLOWED_ORIGINS,
        allow_credentials=True,             # нужно для cookie-сессий
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    app.include_router(auth_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")
    app.include_router(prompts_router, prefix="/api")
    app.include_router(devices_router, prefix="/api")
    app.include_router(ingest_router, prefix="/api")
    app.include_router(streaming_router, prefix="/api")
    app.include_router(realtime_router, prefix="/api")   # WebSocket /api/ws

    # В деве HLS/сегменты отдаёт сам FastAPI; в проде — Nginx напрямую (быстрее).
    app.mount("/hls", StaticFiles(directory=config.HLS_DIR), name="hls")

    # async — чтобы health-check отвечал даже при насыщенном пуле потоков (liveness).
    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.on_event("startup")
    async def _startup():
        # Расширяем пул рабочих потоков (в нём крутятся sync-эндпоинты панели),
        # чтобы всплеск запросов не подвешивал API целиком.
        try:
            import anyio
            anyio.to_thread.current_default_thread_limiter().total_tokens = config.THREADPOOL_TOKENS
        except Exception:  # noqa: BLE001 — не критично для старта
            logger.warning("Не удалось расширить пул потоков", exc_info=True)
        init_db()
        _seed_admin()
        # Фоновая авто-очистка архива по сроку хранения.
        if config.RETENTION_DAYS > 0:
            asyncio.create_task(retention.loop())
            logger.info("Авто-очистка архива включена: хранить %d дн.", config.RETENTION_DAYS)
        # Пассивный монитор пулов/loop — чтобы поймать причину зависаний по логам.
        if config.DIAG_INTERVAL > 0:
            asyncio.create_task(diag.loop(config.DIAG_INTERVAL))
        # Фоновый AI-анализ разговоров (Mistral) — только при наличии ключа.
        if config.ANALYZE and config.MISTRAL_API_KEY:
            asyncio.create_task(analyzer.loop())
            logger.info("AI-анализ разговоров включён (модель %s).", config.MISTRAL_MODEL)
        # Детект тихого отвлечения по кадрам (Pixtral) — при ключе и включённом зрении.
        if config.VISION and config.VISION_SCAN and config.MISTRAL_API_KEY:
            asyncio.create_task(vision_sampler.loop())
            logger.info("Зрение: детект тихого отвлечения включён (модель %s).", config.VISION_MODEL)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
