"""Модели БД: пользователи панели, устройства (камеры), сегменты записи."""
from datetime import datetime, timezone

from sqlalchemy import String, Integer, BigInteger, Float, Boolean, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # Админ видит все камеры и раздаёт доступы; обычный — свою сеть целиком.
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # Сеть студий пользователя: одна на человека. Студии сети могут быть в разных
    # часовых поясах — пояс живёт на студии, а не на человеке.
    network: Mapped[str] = mapped_column(String(128), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Studio(Base):
    """Студия (точка). Камера принадлежит студии, доступ выдаётся тоже на студию.

    Часовой пояс — свойство студии, а не камеры: город один на все её камеры.
    network — сеть («НЕЖНО»), пусто у одиночных студий; нужна только для группировки."""
    __tablename__ = "studios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    network: Mapped[str] = mapped_column(String(128), default="")
    tz: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    devices: Mapped[list["Device"]] = relationship(back_populates="studio")


class PromptOverride(Base):
    """Переопределение промпта ИИ. Разрешается от частного к общему:
    студия → сеть → глобально → встроенный дефолт (см. prompts.py).

    scope: 'studio' (scope_key = id студии), 'network' (scope_key = имя сети,
    например «НЕЖНО»), 'global' (scope_key = ''). Так одна сеть может работать
    по своим правилам, не задевая другую."""
    __tablename__ = "prompt_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(16), default="global")
    scope_key: Mapped[str] = mapped_column(String(128), default="")
    key: Mapped[str] = mapped_column(String(32))       # analyzer_system, analyzer_task, criteria, vision
    text: Mapped[str] = mapped_column(Text, default="")
    updated_by: Mapped[str] = mapped_column(String(64), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


Index("ux_prompt_scope_key", PromptOverride.scope, PromptOverride.scope_key,
      PromptOverride.key, unique=True)


class Device(Base):
    __tablename__ = "devices"

    # device_id, который присылает камера, — естественный первичный ключ
    device_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    studio_id: Mapped[int | None] = mapped_column(
        ForeignKey("studios.id"), nullable=True, index=True
    )
    friendly_name: Mapped[str] = mapped_column(String(128), default="")
    host: Mapped[str] = mapped_column(String(255), default="")
    user: Mapped[str] = mapped_column(String(128), default="")
    last_file: Mapped[str] = mapped_column(String(255), default="")
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    views: Mapped[int] = mapped_column(Integer, default=1)   # число ракурсов (видеодорожек)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    segments: Mapped[list["Segment"]] = relationship(back_populates="device")
    studio: Mapped["Studio | None"] = relationship(back_populates="devices")


class Segment(Base):
    __tablename__ = "segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.device_id"), index=True)
    path: Mapped[str] = mapped_column(String(512))          # путь относительно STORAGE_DIR
    start_ts: Mapped[datetime] = mapped_column(DateTime, index=True)  # начало записи (UTC)
    duration: Mapped[float] = mapped_column(Float, default=0.0)       # секунды
    size: Mapped[int] = mapped_column(BigInteger, default=0)          # байты (видео крупное)
    event: Mapped[str] = mapped_column(String(32), default="normal", index=True)  # тип: normal, zoom, …
    views: Mapped[int] = mapped_column(Integer, default=1)   # число ракурсов в этом сегменте
    idle: Mapped[bool] = mapped_column(Boolean, default=False, index=True)  # простой: картинка не менялась
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    device: Mapped["Device"] = relationship(back_populates="segments")


# Составной индекс для быстрых запросов таймлайна (устройство + диапазон времени)
Index("ix_segments_device_start", Segment.device_id, Segment.start_ts)


class Transcript(Base):
    """Расшифровка речи по сегменту. НЕ привязана внешним ключом к segments —
    хранится по абсолютному времени и НЕ удаляется ретеншеном (живёт вечно),
    даже когда само видео уже вычищено по сроку хранения."""
    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(128), index=True)
    start_ts: Mapped[datetime] = mapped_column(DateTime, index=True)  # абсолютное начало (UTC)
    end_ts: Mapped[datetime] = mapped_column(DateTime)
    text: Mapped[str] = mapped_column(Text)
    words: Mapped[str] = mapped_column(Text, default="")   # JSON пословных таймкодов (опц.)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


Index("ix_transcripts_device_start", Transcript.device_id, Transcript.start_ts)


class Conversation(Base):
    """AI-разбор ЭПИЗОДА (LLM сам делит поток на эпизоды по смыслу).

    kind — тип: consultation/sale/distraction/internal/other. score — общая оценка
    (для консультаций/продаж). data — JSON с остальным разбором (участники, критерии,
    оценка продажника, флаги, вычищенный транскрипт). По абсолютному времени, вечно."""
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(128), index=True)
    start_ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    end_ts: Mapped[datetime] = mapped_column(DateTime)
    kind: Mapped[str] = mapped_column(String(32), default="other", index=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    highlights: Mapped[str] = mapped_column(Text, default="")   # JSON [{t: ms, text, kind}]
    data: Mapped[str] = mapped_column(Text, default="")          # JSON {title,participants,criteria,seller_score,flags,clean}
    embedding: Mapped[str] = mapped_column(Text, default="")     # JSON вектор для семантического поиска
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


Index("ix_conversations_device_start", Conversation.device_id, Conversation.start_ts)


class ScreenEvent(Base):
    """Что было на экране в «тихий» промежуток (есть запись, но речи нет) — по данным
    зрения (Pixtral). Ловит МОЛЧАЛИВОЕ отвлечение (мастер молча смотрит видео/соцсети),
    которое анализатор по речи не видит. Отдельно от conversations, чтобы не двигать
    границу анализатора. По абсолютному времени."""
    __tablename__ = "screen_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(128), index=True)
    start_ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    end_ts: Mapped[datetime] = mapped_column(DateTime)
    activity: Mapped[str] = mapped_column(String(32), default="unknown")  # work|communication|entertainment|idle|unknown
    label: Mapped[str] = mapped_column(String(80), default="")
    distraction: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


Index("ix_screen_events_device_start", ScreenEvent.device_id, ScreenEvent.start_ts)
