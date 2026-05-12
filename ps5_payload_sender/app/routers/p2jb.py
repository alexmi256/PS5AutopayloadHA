"""HTTP endpoints for the P2JB / Patience loader-ready monitor."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

import p2jb_history
from models import P2JBMonitorConfig, P2JBTestRequest
from p2jb_monitor import (
    get_status,
    simulate_loader_ready,
    start_monitor,
    stop_monitor,
    test_notification,
)
from storage import load_p2jb_config, save_p2jb_config

router = APIRouter()
_log = logging.getLogger("ps5_autopayload")


@router.get("/api/p2jb/status")
async def api_p2jb_status():
    return get_status()


@router.get("/api/p2jb/config")
async def api_p2jb_get_config():
    """Last-used monitor settings (persisted across add-on restarts).

    The *running task* is intentionally not persisted — only the form
    values, so the user doesn't have to re-enter ports, flow name, etc.
    every time they open the add-on.
    """
    return load_p2jb_config()


@router.post("/api/p2jb/config")
async def api_p2jb_save_config(cfg: P2JBMonitorConfig):
    save_p2jb_config(cfg.model_dump())
    return {"success": True}


@router.post("/api/p2jb/start")
async def api_p2jb_start(cfg: P2JBMonitorConfig):
    # Persist the config every time the user actually starts a monitor —
    # they've clearly committed to these values.
    save_p2jb_config(cfg.model_dump())
    try:
        status = await start_monitor(cfg)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return status


@router.post("/api/p2jb/stop")
async def api_p2jb_stop():
    return await stop_monitor()


@router.get("/api/p2jb/history")
async def api_p2jb_history():
    """Recent monitor runs (newest-first, capped at MAX_P2JB_HISTORY)."""
    return {"runs": p2jb_history.get_runs()}


@router.delete("/api/p2jb/history")
async def api_p2jb_clear_history():
    p2jb_history.clear_runs()
    return {"success": True}


@router.post("/api/p2jb/test")
async def api_p2jb_test(req: P2JBTestRequest):
    """Send a test notification or simulate the loader-ready event.

    Advanced-Mode tool — never touches the real monitor's running state.
    `event` must be one of:
        loader_ready | flow_started | flow_completed | flow_failed
        simulate_loader_ready
    The first four send a single representative notification. The last one
    additionally broadcasts a UI simulation event and optionally runs the
    selected flow when ``run_real_flow=True``.
    """
    if req.event == "simulate_loader_ready":
        try:
            cfg = P2JBMonitorConfig(
                host=req.host,
                elf_port=req.elf_port,
                flow_name=req.flow_name,
                auto_run=bool(req.run_real_flow and req.flow_name),
                notify_service=req.notify_service,
                notify_loader_ready=req.notify_loader_ready,
                notify_flow_started=req.notify_flow_started,
                notify_flow_completed=req.notify_flow_completed,
                notify_flow_failed=req.notify_flow_failed,
            )
            return await simulate_loader_ready(cfg, run_real_flow=req.run_real_flow)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))

    try:
        return await test_notification(
            req.event,
            notify_service=req.notify_service,
            host=req.host,
            elf_port=req.elf_port,
            flow_name=req.flow_name,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
