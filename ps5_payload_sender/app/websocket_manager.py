"""WebSocket connection manager – singleton `manager` used across all modules."""
from __future__ import annotations

import json
from typing import Set

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._active.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._active.discard(ws)

    async def broadcast(self, message: dict) -> None:
        data = json.dumps(message, ensure_ascii=False)
        dead: Set[WebSocket] = set()
        for ws in list(self._active):
            try:
                await ws.send_text(data)
            except Exception:
                dead.add(ws)
        self._active -= dead

    async def status(self, msg: str, level: str = "info", **extra) -> None:
        await self.broadcast({"type": "status", "level": level, "message": msg, **extra})


# Module-level singleton – import this everywhere
manager = ConnectionManager()
