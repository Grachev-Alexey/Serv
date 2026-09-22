"""Администрирование: студии, привязка камер, пользователи и их доступы.

Всё под `require_admin`. Обычный пользователь сюда не попадает вовсе.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import access
from .db import get_db
from .models import Device, Studio, User
from .security import hash_password

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(access.require_admin)])


# ── Схемы ──────────────────────────────────────────────────────────────────
class StudioIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    network: str = Field(default="", max_length=128)
    tz: str = Field(default="Europe/Moscow", max_length=64)


class StudioOut(BaseModel):
    id: int
    name: str
    network: str
    tz: str
    devices: list[str] = []


class UserIn(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    is_admin: bool = False
    network: str = Field(default="", max_length=128)


class UserOut(BaseModel):
    username: str
    is_admin: bool
    network: str = ""
    created_at: datetime | None = None


class NetworkIn(BaseModel):
    network: str = Field(default="", max_length=128)


# ── Студии ─────────────────────────────────────────────────────────────────
@router.get("/studios", response_model=list[StudioOut])
def list_studios(db: Session = Depends(get_db)):
    out = []
    for s in db.query(Studio).order_by(Studio.network, Studio.name).all():
        ids = [d.device_id for d in db.query(Device).filter(Device.studio_id == s.id).all()]
        out.append(StudioOut(id=s.id, name=s.name, network=s.network, tz=s.tz, devices=ids))
    return out


@router.post("/studios", response_model=StudioOut)
def create_studio(body: StudioIn, db: Session = Depends(get_db)):
    s = Studio(name=body.name.strip(), network=body.network.strip(), tz=body.tz.strip())
    db.add(s)
    db.commit()
    db.refresh(s)
    return StudioOut(id=s.id, name=s.name, network=s.network, tz=s.tz)


@router.patch("/studios/{studio_id}", response_model=StudioOut)
def update_studio(studio_id: int, body: StudioIn, db: Session = Depends(get_db)):
    s = db.get(Studio, studio_id)
    if not s:
        raise HTTPException(status_code=404, detail="Studio not found")
    s.name, s.network, s.tz = body.name.strip(), body.network.strip(), body.tz.strip()
    db.commit()
    access.invalidate()          # часовой пояс/имя видны в панели сразу
    db.refresh(s)
    return StudioOut(id=s.id, name=s.name, network=s.network, tz=s.tz)


@router.delete("/studios/{studio_id}")
def delete_studio(studio_id: int, db: Session = Depends(get_db)):
    s = db.get(Studio, studio_id)
    if not s:
        raise HTTPException(status_code=404, detail="Studio not found")
    n = db.query(Device).filter(Device.studio_id == studio_id).count()
    if n:
        # Не удаляем молча вместе с камерами — сначала перенести их куда-то.
        raise HTTPException(status_code=409, detail=f"К студии привязано камер: {n}")
    db.delete(s)
    db.commit()
    access.invalidate()
    return {"status": "ok"}


@router.patch("/devices/{device_id}/studio")
def assign_device(device_id: str, studio_id: int | None = None, db: Session = Depends(get_db)):
    """Перенос камеры в студию (studio_id=null — отвязать)."""
    d = db.get(Device, device_id)
    if not d:
        raise HTTPException(status_code=404, detail="Device not found")
    if studio_id is not None and not db.get(Studio, studio_id):
        raise HTTPException(status_code=404, detail="Studio not found")
    d.studio_id = studio_id
    db.commit()
    access.invalidate()          # у кого-то могли измениться права на эту камеру
    return {"status": "ok", "device_id": device_id, "studio_id": studio_id}


# ── Пользователи и доступы ─────────────────────────────────────────────────
@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)):
    return [
        UserOut(username=u.username, is_admin=bool(u.is_admin),
                network=u.network or "", created_at=u.created_at)
        for u in db.query(User).order_by(User.username).all()
    ]


@router.post("/users", response_model=UserOut)
def create_user(body: UserIn, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=409, detail="Пользователь уже существует")
    u = User(username=body.username.strip(), password_hash=hash_password(body.password),
             is_admin=body.is_admin, network=body.network.strip())
    db.add(u)
    db.commit()
    access.invalidate(u.username)
    return UserOut(username=u.username, is_admin=bool(u.is_admin), network=u.network or "")


@router.put("/users/{username}/network", response_model=UserOut)
def set_user_network(username: str, body: NetworkIn, db: Session = Depends(get_db)):
    """Привязка пользователя к сети. Пустая строка — доступа нет ни к чему."""
    u = db.query(User).filter(User.username == username).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    net = body.network.strip()
    if net and not db.query(Studio).filter(Studio.network == net).first():
        raise HTTPException(status_code=404, detail=f"Нет студий в сети «{net}»")
    u.network = net
    db.commit()
    access.invalidate(username)
    return UserOut(username=u.username, is_admin=bool(u.is_admin), network=u.network or "")


@router.delete("/users/{username}")
def delete_user(username: str, db: Session = Depends(get_db),
                me: User = Depends(access.require_admin)):
    if username == me.username:
        raise HTTPException(status_code=409, detail="Нельзя удалить самого себя")
    u = db.query(User).filter(User.username == username).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(u)
    db.commit()
    access.invalidate(username)
    return {"status": "ok"}


@router.get("/networks", response_model=list[str])
def list_networks(db: Session = Depends(get_db)):
    rows = db.query(Studio.network).distinct().all()
    return sorted({(r[0] or "").strip() for r in rows if (r[0] or "").strip()})
