"""WebSocket connection manager – singleton `manager` used across all modules."""
from __future__ import annotations

import asyncio
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
        if not self._active:
            return
        data = json.dumps(message, ensure_ascii=False)
        # Fan-out in parallel so a single slow client cannot block the others
        # (HA dashboards on flaky Wi-Fi can take seconds to ack).
        targets = list(self._active)
        results = await asyncio.gather(
            *(ws.send_text(data) for ws in targets),
            return_exceptions=True,
        )
        for ws, result in zip(targets, results):
            if isinstance(result, BaseException):
                self._active.discard(ws)

    async def status(self, msg: str, level: str = "info", **extra) -> None:
        await self.broadcast({"type": "status", "level": level, "message": msg, **extra})


# Module-level singleton – import this everywhere
manager = ConnectionManager()
