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
import time
from pathlib import Path

import fnmatch
import shutil
import urllib.error

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
    HIDDEN_PROFILES,
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
from github_client import (
    download_payload as gh_download_payload,
    get_releases as gh_get_releases,
    get_repo_folders as gh_get_repo_folders,
    scan_repo_files as gh_scan_repo_files,
)
from models import (
    AnalyzePortRequest,
    AutoloadRequest,
    DeviceList,
    FlowAnalyzeRequest,
    ImportPayloadRequest,
    PortCheckRequest,
    SaveProfileRequest,
    SendRequest,
    SourceAddRequest,
    SourceUpdateRequest,
    SwitchVersionRequest,
)
import flow_analysis
from payload_sender import resolve_port, send_payload
from port_checker import check_port, wait_for_port
import port_timing
from storage import (
    build_backup,
    list_payloads,
    list_profiles,
    load_devices,
    load_payload_meta,
    load_sources,
    load_ui_state,
    restore_backup,
    save_devices,
    save_payload_meta,
    save_sources,
    save_ui_state,
    setup_storage,
    trim_versions,
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
    safe = Path(filename).name
    p = PAYLOAD_DIR / safe
    if not p.exists():
        raise HTTPException(404, "Not found")
    p.unlink()
    meta = load_payload_meta()
    if safe in meta:
        del meta[safe]
        save_payload_meta(meta)
    return {"success": True}


# ---------------------------------------------------------------------------
# API – Payload Sources (GitHub)
# ---------------------------------------------------------------------------

@app.get("/api/sources")
async def api_get_sources():
    return {"sources": load_sources()}


@app.get("/api/sources/tree")
async def api_sources_tree(repo: str):
    """Return top-level folder names for a GitHub repository."""
    parts = repo.strip().split("/")
    if len(parts) != 2 or not all(p.strip() for p in parts):
        raise HTTPException(400, "Invalid repository format. Use 'owner/repo'")
    owner, repo_name = parts[0].strip(), parts[1].strip()
    loop = asyncio.get_running_loop()
    try:
        folders = await loop.run_in_executor(executor, gh_get_repo_folders, owner, repo_name)
        return {"folders": folders}
    except urllib.error.HTTPError as exc:
        raise HTTPException(exc.code, f"GitHub API error: HTTP {exc.code}")
    except Exception as exc:
        raise HTTPException(502, str(exc))


@app.post("/api/sources")
async def api_add_source(req: SourceAddRequest):
    parts = req.repo.strip().split("/")
    if len(parts) != 2 or not all(p.strip() for p in parts):
        raise HTTPException(400, "Invalid repository format. Use 'owner/repo'")
    owner, repo_name = parts[0].strip(), parts[1].strip()
    loop = asyncio.get_running_loop()

    assets: list = []

    if req.source_type == "releases":
        # ── Releases only ────────────────────────────────────────
        try:
            assets = await loop.run_in_executor(executor, gh_get_releases, owner, repo_name)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise HTTPException(404, "Repository not found")
            raise HTTPException(502, f"GitHub API error: HTTP {exc.code}")
        except Exception as exc:
            raise HTTPException(502, f"Could not reach GitHub: {exc}")

    elif req.source_type == "folder":
        # ── Specific folder scan ─────────────────────────────────
        folder = req.folder.strip().strip("/") or None
        try:
            assets = await loop.run_in_executor(
                executor, gh_scan_repo_files, owner, repo_name, folder
            )
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise HTTPException(404, "Repository not found")
            raise HTTPException(502, f"GitHub API error: HTTP {exc.code}")
        except Exception as exc:
            raise HTTPException(502, f"Could not reach GitHub: {exc}")

    else:
        # ── Auto: repo files → fall back to releases ─────────────
        try:
            assets = await loop.run_in_executor(executor, gh_scan_repo_files, owner, repo_name)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise HTTPException(404, "Repository not found")
            raise HTTPException(502, f"GitHub API error: HTTP {exc.code}")
        except Exception as exc:
            raise HTTPException(502, f"Could not reach GitHub: {exc}")

        if not assets:
            try:
                assets = await loop.run_in_executor(executor, gh_get_releases, owner, repo_name)
            except Exception as exc:
                raise HTTPException(502, f"GitHub API error: {exc}")

    if not assets:
        raise HTTPException(
            404,
            "No .elf or .lua payload files found. "
            "Try a different source type or folder.",
        )

    if req.filter.strip():
        assets = [a for a in assets if fnmatch.fnmatch(a["asset_name"], req.filter.strip())]
        if not assets:
            raise HTTPException(404, f"No payloads match filter '{req.filter}'")

    slug = f"{owner}/{repo_name}"

    # Build per-asset version list (path preserved for repo_file assets)
    asset_versions: dict = {}
    for a in assets:
        aname = a["asset_name"]
        if aname not in asset_versions:
            asset_versions[aname] = []
        entry: dict = {"tag": a["tag"], "download_url": a["download_url"]}
        if a.get("path"):
            entry["path"] = a["path"]
        if not any(v["tag"] == entry["tag"] for v in asset_versions[aname]):
            asset_versions[aname].append(entry)

    # Auto-link existing local payloads that match asset names
    meta = load_payload_meta()
    auto_linked: list = []
    for aname, versions in asset_versions.items():
        if (PAYLOAD_DIR / aname).exists() and aname not in meta:
            meta[aname] = {
                "repo": slug, "asset": aname,
                "version": versions[0]["tag"], "versions": versions,
            }
            auto_linked.append(aname)
    if auto_linked:
        save_payload_meta(meta)

    sources = load_sources()
    if not any(s["repo"] == slug for s in sources):
        sources.append({
            "repo": slug,
            "filter": req.filter.strip(),
            "source_type": req.source_type,
            "folder": req.folder.strip(),
        })
        save_sources(sources)

    return {"success": True, "repo": slug, "assets": assets, "auto_linked": auto_linked}


@app.delete("/api/sources/{owner}/{repo_name}")
async def api_delete_source(owner: str, repo_name: str):
    slug = f"{owner}/{repo_name}"
    save_sources([s for s in load_sources() if s["repo"] != slug])
    return {"success": True}


@app.put("/api/sources/{owner}/{repo_name}")
async def api_update_source(owner: str, repo_name: str, req: SourceUpdateRequest):
    """Update an existing source's config without re-scanning."""
    slug = f"{owner}/{repo_name}"
    sources = load_sources()
    updated = False
    for s in sources:
        if s["repo"] == slug:
            s["filter"] = req.filter.strip()
            s["source_type"] = req.source_type
            s["folder"] = req.folder.strip()
            updated = True
            break
    if not updated:
        raise HTTPException(404, f"Source '{slug}' not found")
    save_sources(sources)
    return {"success": True, "repo": slug}


@app.get("/api/sources/releases")
async def api_source_releases(repo: str, asset: str = ""):
    parts = repo.strip().split("/")
    if len(parts) != 2:
        raise HTTPException(400, "Use 'owner/repo'")
    owner, repo_name = parts
    loop = asyncio.get_running_loop()
    try:
        assets = await loop.run_in_executor(executor, gh_get_releases, owner, repo_name)
    except Exception as exc:
        raise HTTPException(502, f"GitHub API error: {exc}")
    if asset:
        assets = [a for a in assets if a["asset_name"] == asset]
    return {"releases": assets}


@app.post("/api/payloads/import")
async def api_import_payload(req: ImportPayloadRequest):
    loop = asyncio.get_running_loop()
    try:
        data, actual_name = await loop.run_in_executor(
            executor, gh_download_payload, req.download_url, Path(req.asset_name).name
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Download failed: {exc}")
    safe = Path(actual_name).name
    if Path(safe).suffix.lower() not in ALLOWED_PAYLOAD_EXTENSIONS:
        raise HTTPException(400, "Only .elf and .lua files allowed")
    (PAYLOAD_DIR / safe).write_bytes(data)
    meta = load_payload_meta()
    raw_versions = req.all_versions or [{"tag": req.version, "download_url": req.download_url}]
    meta[safe] = {
        "repo": req.repo, "asset": req.asset_name,
        "version": req.version, "versions": trim_versions(raw_versions),
    }
    save_payload_meta(meta)
    await manager.status(f"'{safe}' imported from {req.repo} {req.version}", level="success")
    return {"success": True, "filename": safe, "size": len(data), "auto_port": resolve_port(safe)}


@app.post("/api/payloads/{filename}/switch-version")
async def api_switch_version(filename: str, req: SwitchVersionRequest):
    safe = Path(filename).name
    dest = PAYLOAD_DIR / safe
    backup_version = ""
    if dest.exists():
        shutil.copy2(dest, PAYLOAD_DIR / f"{safe}.bak")
        backup_version = (load_payload_meta().get(safe) or {}).get("version", "")
    loop = asyncio.get_running_loop()
    try:
        data, _ = await loop.run_in_executor(
            executor, gh_download_payload, req.download_url, safe
        )
    except Exception as exc:
        raise HTTPException(502, f"Download failed: {exc}")
    dest.write_bytes(data)
    meta = load_payload_meta()
    existing = meta.get(safe) or {}
    existing_versions = existing.get("versions", [])
    meta[safe] = {
        **existing,
        "repo": req.repo, "asset": req.asset_name,
        "version": req.version, "backup_version": backup_version,
        "versions": trim_versions(existing_versions),
    }
    save_payload_meta(meta)
    await manager.status(f"'{safe}' switched to {req.version}", level="success")
    return {"success": True, "filename": safe, "version": req.version, "backup_version": backup_version}


@app.post("/api/payloads/{filename}/rollback")
async def api_rollback(filename: str):
    safe = Path(filename).name
    dest   = PAYLOAD_DIR / safe
    backup = PAYLOAD_DIR / f"{safe}.bak"
    if not backup.exists():
        raise HTTPException(404, "No backup found for this payload")
    shutil.copy2(backup, dest)
    meta = load_payload_meta()
    m = meta.get(safe, {})
    prev_ver, current_ver = m.get("backup_version", ""), m.get("version", "")
    m["version"] = prev_ver
    m["backup_version"] = current_ver
    meta[safe] = m
    save_payload_meta(meta)
    await manager.status(f"'{safe}' rolled back to {prev_ver}", level="success")
    return {"success": True, "filename": safe, "version": prev_ver}


@app.get("/api/sources/check-updates")
async def api_check_updates():
    meta = load_payload_meta()
    if not meta:
        return {"updates": [], "checked": 0}
    repos: dict = {}
    for fname, m in meta.items():
        repo = m.get("repo", "")
        if repo:
            repos.setdefault(repo, []).append(fname)
    updates: list = []
    loop = asyncio.get_running_loop()
    for slug, filenames in repos.items():
        parts = slug.split("/")
        if len(parts) != 2:
            continue
        owner, repo_name = parts
        try:
            assets = await loop.run_in_executor(executor, gh_get_releases, owner, repo_name)
            latest_per_asset = {a["asset_name"]: a for a in reversed(assets)}
            for fname in filenames:
                m = meta.get(fname, {})
                current    = m.get("version", "")
                asset_name = m.get("asset", fname)
                latest     = latest_per_asset.get(asset_name)
                if latest and latest["tag"] != current:
                    updates.append({
                        "filename": fname, "current_version": current,
                        "latest_version": latest["tag"],
                        "download_url": latest["download_url"],
                        "repo": slug, "asset_name": asset_name,
                    })
        except Exception:
            pass
    return {"updates": updates, "checked": len(repos)}


@app.get("/api/payloads/{filename}/usage")
async def api_payload_usage(filename: str):
    safe = Path(filename).name
    used_in: list = []
    if PROFILES_DIR.exists():
        for profile in sorted(PROFILES_DIR.iterdir()):
            if not profile.is_file() or profile.suffix.lower() != ".txt":
                continue
            if profile.name in HIDDEN_PROFILES:
                continue
            try:
                for line in profile.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.split()[0] == safe:
                        used_in.append(profile.stem)
                        break
            except Exception:
                pass
    return {"filename": safe, "used_in": used_in}


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
# API – Config Backup / Restore
# ---------------------------------------------------------------------------

@app.get("/api/backup")
async def api_export_backup():
    """Download full configuration as ps5-autopayload-backup.json."""
    from fastapi.responses import Response
    data = json.dumps(build_backup(), ensure_ascii=False, indent=2).encode()
    return Response(
        content=data,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="ps5-autopayload-backup.json"'},
    )


@app.post("/api/backup/restore")
async def api_import_backup(request: Request):
    try:
        data = await request.json()
        if not isinstance(data, dict) or data.get("version") != 1:
            raise HTTPException(400, "Invalid backup file")
    except Exception:
        raise HTTPException(400, "Invalid JSON")
    restore_backup(data)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, write_ha_services_yaml)
    return {"success": True}


# ---------------------------------------------------------------------------
# API – Port Timing
# ---------------------------------------------------------------------------

@app.get("/api/timing")
async def api_get_timing():
    return {"stats": port_timing.get_stats()}


@app.post("/api/timing/record")
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


@app.post("/api/timing/analyze")
async def api_analyze_timing(req: AnalyzePortRequest):
    """Check port, record timing, return result + stats."""
    import time
    start_ts = time.time()
    start_iso = __import__("datetime").datetime.utcnow().isoformat() + "Z"

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
    ready_iso = __import__("datetime").datetime.utcnow().isoformat() + "Z"

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


@app.delete("/api/timing")
async def api_clear_timing():
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, port_timing.clear)
    return {"success": True}


# ---------------------------------------------------------------------------
# API – Log export  (history kept client-side; export endpoint receives it)
# ---------------------------------------------------------------------------

@app.post("/api/logs/export")
async def api_export_logs(request: Request):
    """
    Receive log entries from frontend, return as downloadable file.
    Body: { "entries": [...], "format": "txt" | "json" }
    """
    from fastapi.responses import Response
    body = await request.json()
    entries = body.get("entries", [])
    fmt = body.get("format", "txt")

    if fmt == "json":
        content = json.dumps(entries, ensure_ascii=False, indent=2).encode()
        mime, ext = "application/json", "json"
    else:
        lines = [f"[{e.get('ts', '')}] {e.get('msg', '')}" for e in entries]
        content = "\n".join(lines).encode()
        mime, ext = "text/plain", "txt"

    from datetime import datetime
    stamp = datetime.utcnow().strftime("%Y-%m-%d-%H%M")
    filename = f"ps5-autopayload-log-{stamp}.{ext}"
    return Response(
        content=content,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Flow Analysis
# ---------------------------------------------------------------------------

@app.post("/api/flow/analyze")
async def api_flow_analyze(req: FlowAnalyzeRequest):
    """
    Execute builder steps with per-step timing.
    In safe_mode=True payloads are tracked but not actually sent.
    Returns a full run record with timeline steps.
    """
    if not req.steps:
        raise HTTPException(400, "No steps to analyze")

    run_start   = asyncio.get_event_loop().time()
    wall_start  = time.time()
    steps_out: list = []

    for step in req.steps:
        step_t0  = asyncio.get_event_loop().time()
        offset_s = round(step_t0 - run_start, 2)

        if step.type == "wait_port":
            interval_s = max(0.1, step.interval_ms / 1000)
            t0 = asyncio.get_event_loop().time()
            reached = False
            while asyncio.get_event_loop().time() - t0 < step.timeout:
                if await check_port(req.host, step.port, timeout=2.0):
                    reached = True
                    break
                await asyncio.sleep(interval_s)
            dur_ms = int((asyncio.get_event_loop().time() - step_t0) * 1000)
            steps_out.append({
                "type": "wait_port", "port": step.port,
                "reached": reached, "duration_ms": dur_ms, "offset_s": offset_s,
            })
            if reached:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(executor, port_timing.record, step.port, dur_ms, "", "")

        elif step.type == "delay":
            await asyncio.sleep(step.ms / 1000)
            dur_ms = step.ms
            steps_out.append({
                "type": "delay", "ms": step.ms,
                "duration_ms": dur_ms, "offset_s": offset_s,
            })

        elif step.type == "payload":
            eff_port = step.portOverride or step.autoPort or resolve_port(step.filename, None)
            if req.safe_mode:
                steps_out.append({
                    "type": "payload", "filename": step.filename, "port": eff_port,
                    "safe_mode": True, "success": None, "duration_ms": 0,
                    "offset_s": offset_s,
                })
            else:
                result  = await send_payload(req.host, eff_port, step.filename)
                dur_ms  = int((asyncio.get_event_loop().time() - step_t0) * 1000)
                steps_out.append({
                    "type": "payload", "filename": step.filename, "port": eff_port,
                    "safe_mode": False, "success": result.get("success"),
                    "duration_ms": dur_ms, "offset_s": offset_s,
                })

    total_ms = int((asyncio.get_event_loop().time() - run_start) * 1000)
    run = {
        "id":         int(wall_start * 1000),
        "started_at": wall_start,
        "total_ms":   total_ms,
        "safe_mode":  req.safe_mode,
        "steps":      steps_out,
    }
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, flow_analysis.record_run, run)
    return {"run": run}


@app.get("/api/flow/runs")
async def api_flow_runs():
    loop = asyncio.get_running_loop()
    runs = await loop.run_in_executor(executor, flow_analysis.get_runs)
    return {"runs": runs}


@app.delete("/api/flow/runs")
async def api_flow_clear():
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, flow_analysis.clear_runs)
    return {"success": True}


@app.get("/api/flow/stats")
async def api_flow_stats():
    loop = asyncio.get_running_loop()
    stats = await loop.run_in_executor(executor, flow_analysis.get_stats)
    return stats


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8765, log_level="info", access_log=False)
