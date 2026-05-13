from __future__ import annotations

from fastapi import APIRouter

from models import PortCheckRequest
from port_checker import check_port, wait_for_port
from websocket_manager import manager

router = APIRouter()


@router.post("/api/port/check")
async def api_check_port(req: PortCheckRequest):
    ok = await check_port(req.host, req.port, timeout=req.timeout)
    return {"reachable": ok, "host": req.host, "port": req.port}


@router.post("/api/port/wait")
async def api_wait_port(req: PortCheckRequest):
    await manager.status(
        f"Waiting for port {req.port} on {req.host} (max {req.timeout}s) …",
        waiting_port=req.port,
    )

    async def _prog(elapsed, total):
        await manager.status(
            f"Waiting for port {req.port} … ({elapsed:.0f}/{total:.0f}s)",
            waiting_port=req.port,
        )

    ok = await wait_for_port(
        req.host, req.port,
        total_timeout=req.timeout, interval=req.interval,
        connect_timeout=2.0, progress_callback=_prog,
    )
    msg = f"Port {req.port} reachable!" if ok else f"Timeout: port {req.port} not reachable"
    await manager.status(msg, level="success" if ok else "error")
    return {"reachable": ok, "host": req.host, "port": req.port}
