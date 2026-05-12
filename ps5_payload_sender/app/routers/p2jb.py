"""HTTP endpoints for the P2JB / Patience loader-ready monitor."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from models import P2JBMonitorConfig
from p2jb_monitor import (
    get_status,
    start_monitor,
    stop_monitor,
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
