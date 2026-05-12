from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Request

import port_timing
from exec_engine import executor
from models import AnalyzePortRequest
from port_checker import wait_for_port
from websocket_manager import manager

router = APIRouter()


@router.get("/api/timing")
async def api_get_timing():
    return {"stats": port_timing.get_stats()}


@router.post("/api/timing/record")
async def api_record_timing(request: Request):
    body = await request.json()
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        executor,
        port_timing.record,
        int(body.get("port", 0)),
        int(body.get("duration_ms", 0)),
        body.get("start", ""),
        body.get("ready", ""),
    )
    return {"success": True}


@router.post("/api/timing/analyze")
async def api_analyze_timing(req: AnalyzePortRequest):
    """Check port, record timing, return result + stats."""
    start_ts = time.time()
    start_iso = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"

    async def _prog(elapsed, total):
        await manager.status(
            f"[Analyze] Waiting for port {req.port} … ({elapsed:.0f}/{total:.0f}s)",
            waiting_port=req.port,
        )

    ok = await wait_for_port(
        req.host, req.port,
        total_timeout=req.timeout, interval=req.interval,
        connect_timeout=2.0, progress_callback=_prog,
    )
    duration_ms = int((time.time() - start_ts) * 1000)
    ready_iso = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"

    if ok:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            executor, port_timing.record, req.port, duration_ms, start_iso, ready_iso
        )
        await manager.status(
            f"[Analyze] Port {req.port} reachable in {duration_ms / 1000:.1f}s", level="success"
        )
    else:
        await manager.status(f"[Analyze] Port {req.port} not reachable (timeout)", level="error")

    return {
        "reachable": ok,
        "port": req.port,
        "duration_ms": duration_ms,
        "stats": port_timing.get_port_stats(req.port),
    }


@router.delete("/api/timing")
async def api_clear_timing():
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, port_timing.clear)
    return {"success": True}
