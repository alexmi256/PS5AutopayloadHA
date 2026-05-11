from __future__ import annotations

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from exec_engine import executor
from ha_client import write_ha_services_yaml
from storage import build_backup, reset_config, restore_backup, restore_backup_selective

router = APIRouter()


@router.get("/api/backup")
async def api_export_backup():
    """Download full configuration as ps5-autopayload-backup.json."""
    data = json.dumps(build_backup(), ensure_ascii=False, indent=2).encode()
    return Response(
        content=data,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="ps5-autopayload-backup.json"'},
    )


@router.post("/api/config/reset")
async def api_config_reset():
    """Factory reset: creates a timestamped backup then wipes all user config."""
    result = reset_config()
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, write_ha_services_yaml)
    return result


@router.post("/api/backup/restore")
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


@router.post("/api/backup/restore-selective")
async def api_import_backup_selective(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")
    backup = body.get("backup")
    if not isinstance(backup, dict) or backup.get("version") != 1:
        raise HTTPException(400, "Invalid or missing backup data")
    sections = body.get("sections", ["sources", "payloads", "flows", "profiles", "settings"])
    mode     = body.get("mode", "merge")
    conflict = body.get("conflict", "replace")
    if mode not in ("merge", "replace"):
        raise HTTPException(400, "mode must be 'merge' or 'replace'")
    result = restore_backup_selective(backup, sections, mode, conflict)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, write_ha_services_yaml)
    return {"success": True, **result}


@router.post("/api/logs/export")
async def api_export_logs(request: Request):
    """
    Receive log entries from frontend, return as downloadable file.
    Body: { "entries": [...], "format": "txt" | "json" }
    """
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

    stamp = datetime.utcnow().strftime("%Y-%m-%d-%H%M")
    filename = f"ps5-autopayload-log-{stamp}.{ext}"
    return Response(
        content=content,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
