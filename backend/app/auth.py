"""Авторизация панели: логин/логаут/текущий пользователь."""
import re

from fastapi import APIRouter, Depends, HTTPException, Response, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import config, access
from .db import get_db
from .models import User
from .security import verify_password, create_access_token, get_current_user, get_current_username

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    username: str
    is_admin: bool = False


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=config.COOKIE_NAME,
        value=token,
        max_age=config.JWT_TTL_SECONDS,
        httponly=True,                      # недоступна из JS → защита от XSS-кражи
        secure=config.COOKIE_SECURE,        # только по HTTPS в проде
        samesite=config.COOKIE_SAMESITE,
        path="/",
    )


@router.post("/login", response_model=UserOut)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        # Одинаковый ответ для «нет пользователя» и «неверный пароль».
        raise HTTPException(status_code=401, detail="Invalid credentials")
    _set_session_cookie(response, create_access_token(user.username))
    return UserOut(username=user.username, is_admin=bool(user.is_admin))


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(config.COOKIE_NAME, path="/")
    return {"status": "ok"}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut(username=user.username, is_admin=bool(user.is_admin))


_HLS_URI = re.compile(r"^/hls/([A-Za-z0-9_-]{1,128})/")


@router.get("/hls-auth")
def hls_auth(
    request: Request,
    username: str = Depends(get_current_username),
    db: Session = Depends(get_db),
):
    """Точка для nginx auth_request: 204 при доступе, иначе 401/403.

    Проверяем не только сессию, но и права на КОНКРЕТНУЮ камеру: путь приходит
    от nginx в X-Original-URI (см. deploy/nginx.conf). Без этого любой
    залогиненный мог тянуть чужие камеры прямой ссылкой — id и номера сегментов
    перебираемы, и фильтрация в API ничего бы не дала.

    Права берём из кэша (30 с): субзапрос идёт на каждый .ts, в БД ходить нельзя.
    """
    uri = request.headers.get("X-Original-URI", "")
    m = _HLS_URI.match(uri)
    if not m:
        # nginx не передал путь или он неожиданной формы — не угадываем, отказываем.
        raise HTTPException(status_code=403, detail="Bad HLS path")
    device_id = m.group(1)
    allowed = access.allowed_for_username(db, username)
    if allowed is not None and device_id not in allowed:
        raise HTTPException(status_code=403, detail="Forbidden")
    return Response(status_code=204)
