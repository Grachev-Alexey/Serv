"""Подключение к БД (SQLite через SQLAlchemy)."""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from . import config

# SQLite требует check_same_thread=False; для PostgreSQL — просторный пул с
# pre-ping и, главное, с connect_timeout: удалённая БД не должна вешать процесс.
_is_sqlite = config.DATABASE_URL.startswith("sqlite")
if _is_sqlite:
    engine = create_engine(
        config.DATABASE_URL,
        connect_args={"check_same_thread": False},
        future=True,
    )
else:
    engine = create_engine(
        config.DATABASE_URL,
        # connect_timeout — БЕЗ него зависшая удалённая БД блокирует чекаут
        # соединения на минуты (TCP-таймаут ОС) и подвешивает все sync-эндпоинты.
        connect_args={"connect_timeout": config.DB_CONNECT_TIMEOUT},
        pool_pre_ping=True,
        pool_size=config.DB_POOL_SIZE,
        max_overflow=config.DB_MAX_OVERFLOW,
        pool_timeout=config.DB_POOL_TIMEOUT,   # не ждать соединение бесконечно
        pool_recycle=config.DB_POOL_RECYCLE,
        future=True,
    )
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI-зависимость: сессия на запрос."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from . import models  # noqa: F401 — регистрируем модели перед create_all
    Base.metadata.create_all(bind=engine)
    # Лёгкие миграции для уже существующих таблиц (Postgres): новые колонки + индексы.
    # ВАЖНО: составной индекс объявлен в models.py, но create_all его НЕ создаёт для
    # уже существующей таблицы segments → без него каждый запрос таймлайна/кадра —
    # это скан удалённой БД (медленно, соединения держатся дольше → пул выедается).
    if engine.dialect.name == "postgresql":
        for ddl in (
            "ALTER TABLE segments ADD COLUMN IF NOT EXISTS event VARCHAR(32) DEFAULT 'normal'",
            "ALTER TABLE segments ADD COLUMN IF NOT EXISTS views INTEGER DEFAULT 1",
            "ALTER TABLE segments ADD COLUMN IF NOT EXISTS idle BOOLEAN DEFAULT FALSE",
            "ALTER TABLE devices ADD COLUMN IF NOT EXISTS views INTEGER DEFAULT 1",
            "CREATE INDEX IF NOT EXISTS ix_segments_device_start ON segments (device_id, start_ts)",
            # v2-разбор эпизодов: обогащаем таблицу conversations (если создана в Фазе A).
            "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS kind VARCHAR(32) DEFAULT 'other'",
            "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS score INTEGER",
            "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS data TEXT DEFAULT ''",
            "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS embedding TEXT DEFAULT ''",
            # Мультиаккаунтинг: студии (точки), привязка камер, права пользователей.
            # Часовой пояс держим на студии — город один на все её камеры.
            "ALTER TABLE devices ADD COLUMN IF NOT EXISTS studio_id INTEGER REFERENCES studios(id)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE",
            "CREATE INDEX IF NOT EXISTS ix_devices_studio_id ON devices (studio_id)",
            # Доступ выдаётся сетью: человек = одна сеть студий. Часовой пояс при
            # этом остаётся на студии — сеть может жить в нескольких поясах.
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS network VARCHAR(128) NOT NULL DEFAULT ''",
            "CREATE INDEX IF NOT EXISTS ix_users_network ON users (network)",
            "DROP TABLE IF EXISTS user_studios",
            # Индексы, объявленные в models.py: create_all не создаёт их для уже
            # существующей таблицы, а колонки добавлялись через ALTER выше.
            "CREATE INDEX IF NOT EXISTS ix_segments_event ON segments (event)",
            "CREATE INDEX IF NOT EXISTS ix_segments_idle ON segments (idle)",
            # Редактируемые промпты ИИ (глобально / на сеть / на студию).
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_prompt_scope_key "
            "ON prompt_overrides (scope, scope_key, key)",
        ):
            try:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
            except Exception:  # noqa: BLE001 — миграция не критична для старта
                pass
