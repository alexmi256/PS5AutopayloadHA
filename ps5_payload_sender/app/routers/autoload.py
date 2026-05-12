from __future__ import annotations

import asyncio
import io
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from atomic_write import atomic_write_text
from autoload_parser import (
    DelayDirective,
    NotifyDirective,
    SendDirective,
    WaitForLoaderDirective,
    WaitPortDirective,
    parse_autoload_path,
    parse_notify_config,
    parse_version_pins,
    set_version_pin,
)
from config import PAYLOAD_DIR, PROFILES_DIR
from exec_engine import (
    ExecState,
    executor,
    get_exec_state,
    request_pause,
    request_resume,
    request_stop,
    run_autoload,
    set_exec_state,
)
from ha_client import write_ha_services_yaml
from models import AutoloadRequest, PatchFlowVersionsRequest, SaveProfileRequest
from payload_sender import resolve_port
from storage import list_profiles
from websocket_manager import manager

router = APIRouter()


@router.get("/api/autoload/profiles")
async def api_get_profiles():
    return {"profiles": list_profiles()}


@router.get("/api/autoload/content/{profile}")
async def api_get_profile_content(profile: str):
    p = PROFILES_DIR / Path(profile).name
    if not p.exists():
        raise HTTPException(404, "Profile not found")
    return {"content": p.read_text(encoding="utf-8", errors="replace"), "profile": p.name}


@router.post("/api/autoload/content")
async def api_save_profile(req: SaveProfileRequest):
    safe = Path(req.profile).name
    if not safe.endswith(".txt"):
        raise HTTPException(400, "Only .txt files allowed")
    atomic_write_text(PROFILES_DIR / safe, req.content)
    await manager.status(f"Profile '{safe}' saved", level="success")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, write_ha_services_yaml)
    return {"success": True}


@router.delete("/api/autoload/content/{profile}")
async def api_delete_profile(profile: str):
    p = PROFILES_DIR / Path(profile).name
    if not p.exists():
        raise HTTPException(404, "Profile not found")
    p.unlink()
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, write_ha_services_yaml)
    return {"success": True}


@router.get("/api/autoload/parse/{profile}")
async def api_parse_profile(profile: str):
    p = PROFILES_DIR / Path(profile).name
    if not p.exists():
        raise HTTPException(404, "Profile not found")
    content      = p.read_text(encoding="utf-8", errors="replace")
    version_pins = parse_version_pins(content)
    notify_cfg   = parse_notify_config(content)
    steps = []
    for d in parse_autoload_path(p):
        if isinstance(d, SendDirective):
            steps.append({
                "type": "payload",
                "filename": d.filename,
                "autoPort": resolve_port(d.filename),
                "portOverride": d.port,
                "version": version_pins.get(d.filename),
            })
        elif isinstance(d, DelayDirective):
            steps.append({"type": "delay", "ms": d.milliseconds})
        elif isinstance(d, WaitPortDirective):
            steps.append({
                "type": "wait_port",
                "port": d.port,
                "timeout": d.timeout_seconds,
                "interval_ms": d.interval_ms,
            })
        elif isinstance(d, WaitForLoaderDirective):
            # Legacy `??9021 7200 30 1` flows carried their loader config
            # on the step. The new model puts everything in the ~notify
            # header — promote step-level overrides into notify_cfg here
            # so the UI sees a single source of truth. Each axis is
            # promoted independently: if the header already has an
            # explicit non-default value, leave the step value in place
            # (engine will still respect it).
            out_port      = d.port
            out_max_wait  = d.max_wait_seconds
            out_interval  = d.interval_seconds
            promoted = False
            if d.port and notify_cfg.get("loader_port", 9021) == 9021:
                notify_cfg["loader_port"] = d.port
                out_port = 0
                promoted = True
            if d.max_wait_seconds and notify_cfg.get("loader_max_wait_s", 10800) == 10800:
                notify_cfg["loader_max_wait_s"] = int(d.max_wait_seconds)
                out_max_wait = 0
                promoted = True
            if d.interval_seconds and notify_cfg.get("loader_interval_s", 30) == 30:
                notify_cfg["loader_interval_s"] = int(d.interval_seconds)
                out_interval = 0
                promoted = True
            if promoted:
                # Without this the migration would be silent — the step
                # could land in a flow whose loader_ready was off.
                notify_cfg["loader_ready"] = True
            steps.append({
                "type": "wait_for_loader",
                "port": out_port,
                "max_wait_s": out_max_wait,
                "interval_s": out_interval,
                "stability_count": d.stability_count,
            })
        elif isinstance(d, NotifyDirective):
            steps.append({
                "type": "notify",
                "title": d.title,
                "message": d.message,
                "service_override": d.service_override or "",
            })
    return {
        "steps":         steps,
        "profile":       p.name,
        "version_pins":  version_pins,
        "notify_config": notify_cfg,
    }


@router.post("/api/autoload/patch-versions/{profile}")
async def api_patch_flow_versions(profile: str, req: PatchFlowVersionsRequest):
    p = PROFILES_DIR / Path(profile).name
    if not p.exists():
        raise HTTPException(404, "Profile not found")
    content = p.read_text(encoding="utf-8", errors="replace")
    content = set_version_pin(content, req.filename, req.version)
    atomic_write_text(p, content)
    return {"ok": True}


@router.post("/api/autoload/export-zip")
async def api_export_autoload_zip(request: Request):
    """Build ps5_autoloader/<files> ZIP ready to extract directly onto a USB stick."""
    data          = await request.json()
    autoload_txt: str  = data.get("autoload_txt", "")
    payloads: list     = data.get("payloads", [])

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("ps5_autoloader/autoload.txt", autoload_txt)
        for fname in payloads:
            safe = Path(fname).name
            path = PAYLOAD_DIR / safe
            if path.exists() and path.is_file():
                zf.write(str(path), f"ps5_autoloader/{safe}")

    buf.seek(0)
    return Response(
        content=buf.read(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="autoload.zip"'},
    )


@router.get("/api/autoload/state")
async def api_get_exec_state():
    return {"state": get_exec_state()}


@router.post("/api/autoload/run")
async def api_run_autoload(req: AutoloadRequest):
    try:
        return await run_autoload(req)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))


@router.post("/api/autoload/stop")
async def api_stop_autoload():
    request_stop()
    await manager.status("Stop requested …", level="warn")
    return {"success": True}


@router.post("/api/autoload/pause")
async def api_pause_autoload():
    if not request_pause():
        return {"success": False, "message": "Not running"}
    await set_exec_state(ExecState.PAUSED)
    await manager.status("Execution paused ⏸", level="warn")
    return {"success": True}


@router.post("/api/autoload/resume")
async def api_resume_autoload():
    if not request_resume():
        return {"success": False, "message": "Not paused"}
    await set_exec_state(ExecState.RUNNING)
    await manager.status("Execution resumed ▶", level="success")
    return {"success": True}
