"""Реалтайм-обновления панели через WebSocket.

Один процесс (uvicorn --workers 1) держит все сокеты. При новом сегменте
ingest вызывает broadcast_soon(...) — панель мгновенно перезапрашивает данные.
Авторизация — по той же cookie-сессии, что и обычный API.
"""
import json
import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import config
from .security import _decode_token

logger = logging.getLogger("monitoring.realtime")
router = APIRouter()


class Hub:
    """Набор активных WebSocket-подключений панели."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    def add(self, ws: WebSocket) -> None:
        self._clients.add(ws)

    def remove(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def broadcast(self, message: dict) -> None:
        if not self._clients:
            return
        data = json.dumps(message)
        for ws in list(self._clients):
            try:
                await ws.send_text(data)
            except Exception:  # noqa: BLE001 — мёртвое соединение выкидываем
                self.remove(ws)


hub = Hub()


def broadcast_soon(message: dict) -> None:
    """Отправить событие, не дожидаясь доставки (fire-and-forget в текущем loop)."""
    try:
        asyncio.get_running_loop().create_task(hub.broadcast(message))
    except RuntimeError:
        pass  # нет активного loop — событие просто не отправится


@router.websocket("/ws")
async def ws_updates(websocket: WebSocket) -> None:
    token = websocket.cookies.get(config.COOKIE_NAME)
    if not token or not _decode_token(token):
        await websocket.close(code=1008)  # policy violation — нет валидной сессии
        return
    await websocket.accept()
    hub.add(websocket)
    try:
        while True:
            await websocket.receive_text()  # клиентские сообщения (ping) игнорируем
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        pass
    finally:
        hub.remove(websocket)
