"""
PS5 Payload Sender – FastAPI entry point (v3.11)

This file is intentionally thin: app creation, startup hook, route handlers,
WebSocket endpoint, and static-file mount.  All heavy logic lives in focused modules:

  config.py            – constants & env vars
  models.py            – Pydantic request models
  ha_component.py      – HA custom component generator
  ha_client.py         – HA Supervisor API helpers
  storage.py           – file I/O (payloads, profiles, devices, UI state)
  websocket_manager.py – ConnectionManager singleton
  exec_engine.py       – execution state machine + autoload runner
"""
from __future__ import annotations

import asyncio
import json
import logging
import logging.handlers
from pathlib import Path

import aiofiles
import uvicorn
from fastapi import (
    FastAPI,
    File,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

import payload_sender as _ps_module
from autoload_parser import DelayDirective, SendDirective, WaitPortDirective, parse_autoload_path
from config import (
    APP_VERSION,
    ALLOWED_PAYLOAD_EXTENSIONS,
    CONFIG_BASE,
    HOST,
    PAYLOAD_DIR,
    PORT_CHECK_INTERVAL,
    PORT_CHECK_TIMEOUT,
    PROFILES_DIR,
    STATIC_DIR,
    SUPERVISOR_TOKEN,
)
from payload_sender import DEFAULT_ELF_PORT, DEFAULT_LUA_PORT
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
from ha_client import (
    debug_ha_push,
    get_remote_version,
    push_ha_state,
    reload_integration,
    write_ha_services_yaml,
)
from models import (
    AutoloadRequest,
    DeviceList,
    PortCheckRequest,
    SaveProfileRequest,
    SendRequest,
)
from payload_sender import resolve_port, send_payload
from port_checker import check_port, wait_for_port
from storage import (
    list_payloads,
    list_profiles,
    load_devices,
    load_ui_state,
    save_devices,
    save_ui_state,
    setup_storage,
)
from websocket_manager import manager

# ---------------------------------------------------------------------------
# Logging – file + stream, auto-rotate at 2 MB, keep 3 backups
# ---------------------------------------------------------------------------

def _setup_logging() -> logging.Logger:
    _log_dir = Path("/config/ps5_autopayload")
    _log_dir.mkdir(parents=True, exist_ok=True)
    _log_file = _log_dir / "ps5_autopayload.log"

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh = logging.handlers.RotatingFileHandler(
        _log_file, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    sh.setLevel(logging.INFO)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    if not root.handlers:
        root.addHandler(fh)
        root.addHandler(sh)

    return logging.getLogger("ps5_autopayload")


_log = _setup_logging()

# ---------------------------------------------------------------------------
# One-time setup
# ---------------------------------------------------------------------------

setup_storage()

# Patch payload_sender so send_payload finds files in the right location
_ps_module.PAYLOAD_DIR = PAYLOAD_DIR

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="PS5 Autopayload", version=APP_VERSION)


@app.on_event("startup")
async def _on_startup() -> None:
    _log.info("PS5 Autopayload v%s starting up", APP_VERSION)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, push_ha_state, ExecState.IDLE)
    await loop.run_in_executor(executor, write_ha_services_yaml)
    _log.info("Startup complete")


# ---------------------------------------------------------------------------
# Root – inject ingress base path
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    ingress_path = request.headers.get("X-Ingress-Path", "").rstrip("/")
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    inject = f'<script>window.PS5_BASE="{ingress_path}";</script>'
    return HTMLResponse(content=html.replace("</head>", inject + "\n</head>", 1))


# ---------------------------------------------------------------------------
# API – Version
# ---------------------------------------------------------------------------

@app.get("/api/version")
async def api_get_version():
    return {"version": APP_VERSION}


@app.get("/api/version/check")
async def api_check_version():
    loop = asyncio.get_running_loop()
    remote = await loop.run_in_executor(executor, get_remote_version)
    up_to_date = (not remote) or (remote == APP_VERSION)
    return {"current": APP_VERSION, "remote": remote, "up_to_date": up_to_date}


# ---------------------------------------------------------------------------
# API – Config
# ---------------------------------------------------------------------------

@app.get("/api/config")
async def api_get_config():
    return {
        "ps5_ip": HOST,
        "lua_port": DEFAULT_LUA_PORT,
        "elf_port": DEFAULT_ELF_PORT,
        "port_check_timeout": PORT_CHECK_TIMEOUT,
        "port_check_interval": PORT_CHECK_INTERVAL,
    }


# ---------------------------------------------------------------------------
# API – UI State
# ---------------------------------------------------------------------------

@app.get("/api/state")
async def api_get_state():
    return load_ui_state()


@app.post("/api/state")
async def api_post_state(request: Request):
    save_ui_state(await request.json())
    return {"success": True}


# ---------------------------------------------------------------------------
# API – Devices
# ---------------------------------------------------------------------------

@app.get("/api/devices")
async def api_get_devices():
    return {"devices": load_devices()}


@app.post("/api/devices")
async def api_post_devices(req: DeviceList):
    save_devices(req.devices)
    return {"success": True}


# ---------------------------------------------------------------------------
# API – Payloads
# ---------------------------------------------------------------------------

@app.get("/api/payloads")
async def api_list_payloads():
    return {"payloads": list_payloads()}


@app.post("/api/payloads/upload")
async def api_upload(file: UploadFile = File(...)):
    safe = Path(file.filename).name
    ext = Path(safe).suffix.lower()
    if ext not in ALLOWED_PAYLOAD_EXTENSIONS:
        raise HTTPException(400, f"Type '{ext}' not allowed — only .lua and .elf files")
    content = await file.read()
    async with aiofiles.open(PAYLOAD_DIR / safe, "wb") as f:
        await f.write(content)
    await manager.status(f"'{safe}' uploaded ({len(content)} bytes)", level="success")
    return {"success": True, "filename": safe, "size": len(content), "auto_port": resolve_port(safe)}


@app.delete("/api/payloads/{filename}")
async def api_delete_payload(filename: str):
    p = PAYLOAD_DIR / Path(filename).name
    if not p.exists():
        raise HTTPException(404, "Not found")
    p.unlink()
    return {"success": True}


# ---------------------------------------------------------------------------
# API – Send
# ---------------------------------------------------------------------------

@app.post("/api/send")
async def api_send(req: SendRequest):
    port = resolve_port(req.filename, req.port)
    await manager.status(f"Sending '{req.filename}' → {req.host}:{port} …")
    result = await send_payload(req.host, port, req.filename)
    await manager.status(result["message"], level="success" if result["success"] else "error")
    return result


# ---------------------------------------------------------------------------
# API – Autoload profiles
# ---------------------------------------------------------------------------

@app.get("/api/autoload/profiles")
async def api_get_profiles():
    return {"profiles": list_profiles()}


@app.get("/api/autoload/content/{profile}")
async def api_get_profile_content(profile: str):
    p = PROFILES_DIR / Path(profile).name
    if not p.exists():
        raise HTTPException(404, "Profile not found")
    return {"content": p.read_text(encoding="utf-8", errors="replace"), "profile": p.name}


@app.post("/api/autoload/content")
async def api_save_profile(req: SaveProfileRequest):
    safe = Path(req.profile).name
    if not safe.endswith(".txt"):
        raise HTTPException(400, "Only .txt files allowed")
    (PROFILES_DIR / safe).write_text(req.content, encoding="utf-8")
    await manager.status(f"Profile '{safe}' saved", level="success")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, write_ha_services_yaml)
    return {"success": True}


@app.delete("/api/autoload/content/{profile}")
async def api_delete_profile(profile: str):
    p = PROFILES_DIR / Path(profile).name
    if not p.exists():
        raise HTTPException(404, "Profile not found")
    p.unlink()
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, write_ha_services_yaml)
    return {"success": True}


@app.get("/api/autoload/parse/{profile}")
async def api_parse_profile(profile: str):
    p = PROFILES_DIR / Path(profile).name
    if not p.exists():
        raise HTTPException(404, "Profile not found")
    steps = []
    for d in parse_autoload_path(p):
        if isinstance(d, SendDirective):
            steps.append({
                "type": "payload",
                "filename": d.filename,
                "autoPort": resolve_port(d.filename),
                "portOverride": d.port,
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
    return {"steps": steps, "profile": p.name}


# ---------------------------------------------------------------------------
# API – Autoload execution
# ---------------------------------------------------------------------------

@app.get("/api/autoload/state")
async def api_get_exec_state():
    return {"state": get_exec_state()}


@app.post("/api/autoload/run")
async def api_run_autoload(req: AutoloadRequest):
    try:
        return await run_autoload(req)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))


@app.post("/api/autoload/stop")
async def api_stop_autoload():
    request_stop()
    await manager.status("Stop requested …", level="warn")
    return {"success": True}


@app.post("/api/autoload/pause")
async def api_pause_autoload():
    if not request_pause():
        return {"success": False, "message": "Not running"}
    await set_exec_state(ExecState.PAUSED)
    await manager.status("Execution paused ⏸", level="warn")
    return {"success": True}


@app.post("/api/autoload/resume")
async def api_resume_autoload():
    if not request_resume():
        return {"success": False, "message": "Not paused"}
    await set_exec_state(ExecState.RUNNING)
    await manager.status("Execution resumed ▶", level="success")
    return {"success": True}


# ---------------------------------------------------------------------------
# API – Port check
# ---------------------------------------------------------------------------

@app.post("/api/port/check")
async def api_check_port(req: PortCheckRequest):
    ok = await check_port(req.host, req.port, timeout=req.timeout)
    return {"reachable": ok, "host": req.host, "port": req.port}


@app.post("/api/port/wait")
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


# ---------------------------------------------------------------------------
# API – Home Assistant integration helpers
# ---------------------------------------------------------------------------

@app.post("/api/ha/push")
async def api_ha_push():
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, push_ha_state, get_exec_state())
    return {"success": True, "state": get_exec_state(), "supervisor_token": bool(SUPERVISOR_TOKEN)}


@app.get("/api/ha/debug")
async def api_ha_debug():
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, debug_ha_push, get_exec_state())


@app.get("/api/ha/logs")
async def api_ha_logs(lines: int = 200):
    log_file = CONFIG_BASE / "ps5_autopayload.log"
    if not log_file.exists():
        return {"lines": [], "error": "Log file not found"}
    try:
        async with aiofiles.open(log_file, "r", encoding="utf-8", errors="replace") as f:
            content = await f.read()
        all_lines = content.splitlines()
        return {"lines": all_lines[-lines:], "total": len(all_lines)}
    except Exception as exc:
        return {"lines": [], "error": str(exc)}


@app.post("/api/ha/reload-integration")
async def api_reload_integration():
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, write_ha_services_yaml)
    return await loop.run_in_executor(executor, reload_integration)


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await manager.connect(ws)
    await ws.send_text(json.dumps({
        "type": "config",
        "ps5_ip": HOST,
        "lua_port": DEFAULT_LUA_PORT,
        "elf_port": DEFAULT_ELF_PORT,
    }))
    try:
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await ws.send_text(json.dumps({"type": "pong"}))
            except Exception:
                pass
    except WebSocketDisconnect:
        manager.disconnect(ws)


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8765, log_level="info", access_log=False)
