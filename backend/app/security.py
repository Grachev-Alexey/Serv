"""Хеширование паролей и JWT-сессии в httpOnly-cookie."""
from datetime import datetime, timezone, timedelta

import jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from . import config
from .db import get_db
from .models import User

# pbkdf2_sha256 — чистый Python, без нативных зависимостей и проблем совместимости.
_pwd = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _pwd.verify(password, password_hash)


def create_access_token(username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + timedelta(seconds=config.JWT_TTL_SECONDS),
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def _decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Зависимость: достаёт пользователя из cookie-сессии либо отдаёт 401."""
    token = request.cookies.get(config.COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username = _decode_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return user


def get_current_username(request: Request) -> str:
    """Лёгкая проверка сессии по cookie БЕЗ обращения к БД — для частых субзапросов
    (nginx auth_request на КАЖДЫЙ .ts/.jpg). Достаточно валидной подписи JWT."""
    token = request.cookies.get(config.COOKIE_NAME)
    username = _decode_token(token) if token else None
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return username
