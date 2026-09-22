"""Управление устройствами: список камер и переименование."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import config
from .db import get_db
from .models import Device, User
from .security import get_current_user
from .access import visible_devices, require_device

router = APIRouter(prefix="/devices", tags=["devices"])


class DeviceOut(BaseModel):
    device_id: str
    friendly_name: str
    host: str
    user: str
    last_file: str
    last_seen: datetime | None
    online: bool
    views: int
    studio_id: int | None = None
    studio: str = ""            # «Пролетарская»
    network: str = ""           # «НЕЖНО» — для группировки в панели
    tz: str = "Europe/Moscow"   # часовой пояс студии: время камеры, а не браузера


class RenameRequest(BaseModel):
    friendly_name: str = Field(min_length=1, max_length=128)


def _to_out(d: Device) -> DeviceOut:
    online = False
    last_seen = d.last_seen
    if last_seen is not None:
        # last_seen хранится наивным UTC — трактуем как UTC при сравнении.
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - last_seen).total_seconds()
        online = age <= config.DEVICE_ONLINE_SECONDS
    return DeviceOut(
        device_id=d.device_id,
        friendly_name=d.friendly_name or d.device_id,
        host=d.host,
        user=d.user,
        last_file=d.last_file,
        last_seen=d.last_seen,
        online=online,
        views=d.views or 1,
        studio_id=d.studio_id,
        studio=(d.studio.name if d.studio else ""),
        network=(d.studio.network if d.studio else ""),
        tz=(d.studio.tz if d.studio else "Europe/Moscow"),
    )


@router.get("", response_model=list[DeviceOut])
def list_devices(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Только камеры студий, выданных пользователю (админу — все)."""
    return [_to_out(d) for d in visible_devices(db, user)]


@router.patch("/{device_id}", response_model=DeviceOut)
def rename_device(
    device_id: str,
    body: RenameRequest,
    db: Session = Depends(get_db),
    _: str = Depends(require_device),
):
    device = db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    device.friendly_name = body.friendly_name.strip()
    db.commit()
    db.refresh(device)
    return _to_out(device)
