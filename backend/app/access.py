"""Права доступа к камерам: человек → сеть студий → камеры.

Единственная точка контроля. Все эндпоинты, отдающие данные конкретной камеры,
идут через `require_device`, списки — через `visible_devices`.

Человек привязан к одной сети и видит все её студии. Часовой пояс при этом
остаётся свойством студии: одна сеть спокойно живёт в нескольких поясах.
Камера без студии видна только админу — иначе новая точка утекала бы всем.
"""
import time

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from .db import get_db
from .models import Device, Studio, User
from .security import get_current_user


def allowed_device_ids(db: Session, user: User) -> set[str] | None:
    """Камеры пользователя. None — доступны все (админ), иначе множество id."""
    if user.is_admin:
        return None
    if not (user.network or "").strip():
        return set()
    rows = (
        db.query(Device.device_id)
        .join(Studio, Device.studio_id == Studio.id)
        .filter(Studio.network == user.network)
        .all()
    )
    return {r[0] for r in rows}


def visible_devices(db: Session, user: User) -> list[Device]:
    """Камеры, которые пользователю можно показать, свежие сверху."""
    q = db.query(Device)
    if not user.is_admin:
        if not (user.network or "").strip():
            return []
        q = q.join(Studio, Device.studio_id == Studio.id).filter(Studio.network == user.network)
    return q.order_by(Device.last_seen.desc()).all()


def can_access(db: Session, user: User, device_id: str) -> bool:
    if user.is_admin:
        return True
    if not (user.network or "").strip():
        return False
    dev = db.get(Device, device_id)
    if dev is None or not dev.studio_id:
        return False
    st = db.get(Studio, dev.studio_id)
    return st is not None and st.network == user.network


def require_device(
    device_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> str:
    """Зависимость для эндпоинтов вида /devices/{device_id}/…

    Отдаём 404, а не 403: посторонний не должен по коду ответа узнавать,
    существует ли такая камера вообще.
    """
    if not can_access(db, user, device_id):
        raise HTTPException(status_code=404, detail="Device not found")
    return device_id


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin required")
    return user


# ── Быстрая проверка для nginx auth_request ────────────────────────────────
# Субзапрос идёт на КАЖДЫЙ .ts и .jpg — при просмотре архива это десятки в
# секунду. Ходить в БД каждый раз нельзя, поэтому держим короткий кэш прав.
_CACHE_TTL = 30.0
_cache: dict[str, tuple[float, set[str] | None]] = {}


def allowed_for_username(db: Session, username: str) -> set[str] | None:
    """Права по имени пользователя, с кэшем. None — доступно всё (админ).

    Отзыв доступа применяется в течение TTL; критичные ручки ходят в БД напрямую.
    """
    now = time.monotonic()
    hit = _cache.get(username)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    user = db.query(User).filter(User.username == username).first()
    ids = allowed_device_ids(db, user) if user else set()
    _cache[username] = (now, ids)
    return ids


def invalidate(username: str | None = None) -> None:
    """Сбросить кэш прав — после смены сети, переноса камеры или удаления студии."""
    if username is None:
        _cache.clear()
    else:
        _cache.pop(username, None)
