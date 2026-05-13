from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from exec_engine import executor
from ha_client import write_ha_services_yaml
from storage import (
    build_backup_zip,
    parse_backup_archive,
    reset_config,
    restore_backup,
    restore_backup_payloads,
    restore_backup_selective,
)

router = APIRouter()


@router.get("/api/backup")
async def api_export_backup():
    """Download full configuration as a ZIP archive containing
    backup.json AND every installed payload binary (so a restore on
    a clean instance doesn't need to re-fetch from GitHub and
    preserves any manually-uploaded payloads).

    Legacy JSON-only backups are still accepted on import — see
    /api/backup/restore.
    """
    data = build_backup_zip()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M")
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition":
                f'attachment; filename="ps5-autopayload-backup-{stamp}.zip"',
        },
    )


@router.post("/api/config/reset")
async def api_config_reset():
    """Factory reset: creates a timestamped backup then wipes all user config."""
    result = reset_config()
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, write_ha_services_yaml)
    return result


@router.post("/api/backup/inspect")
async def api_inspect_backup(request: Request):
    """Peek inside an uploaded backup (ZIP or JSON) without applying
    anything. Returns the parsed `backup.json` so the frontend can
    show a preview before the user confirms. Used to keep the ZIP
    parsing on the server side (no JSZip dependency in the browser).
    """
    raw = await request.body()
    if not raw:
        raise HTTPException(400, "Empty request body")
    try:
        backup, payloads = parse_backup_archive(raw)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {
        "backup":          backup,
        "payload_count":   len(payloads),
        "payload_names":   sorted(payloads.keys()),
    }


@router.post("/api/backup/restore")
async def api_import_backup(request: Request):
    """Accepts either a ZIP archive (new format with payload binaries)
    or a legacy JSON body. Auto-detects via PK magic bytes."""
    raw = await request.body()
    if not raw:
        raise HTTPException(400, "Empty request body")
    try:
        data, payloads = parse_backup_archive(raw)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise HTTPException(400, "Invalid backup file (missing version=1)")
    restore_backup(data)
    written = restore_backup_payloads(payloads)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, write_ha_services_yaml)
    return {"success": True, "payloads_restored": written}


@router.post("/api/backup/restore-selective")
async def api_import_backup_selective(request: Request):
    """Selective restore. Body can be:

      * JSON object ``{backup, sections, mode, conflict}`` — legacy
      * ZIP archive — sections / mode / conflict are taken from
        query params or fall back to defaults
    """
    raw = await request.body()
    if not raw:
        raise HTTPException(400, "Empty request body")

    # ZIP form: read sections/mode/conflict from query params
    if raw[:4] == b"PK\x03\x04":
        try:
            backup, payloads = parse_backup_archive(raw)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        q = request.query_params
        sections_raw = q.get("sections", "sources,payloads,flows,profiles,settings")
        sections = [s.strip() for s in sections_raw.split(",") if s.strip()]
        mode     = q.get("mode", "merge")
        conflict = q.get("conflict", "replace")
        include_payload_files = q.get("include_payload_files", "1") not in ("0", "false", "no")
    else:
        # Legacy JSON wrapper
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            raise HTTPException(400, "Invalid JSON")
        backup = body.get("backup")
        if not isinstance(backup, dict):
            raise HTTPException(400, "Invalid or missing backup data")
        payloads = {}
        sections = body.get("sections", ["sources", "payloads", "flows", "profiles", "settings"])
        mode     = body.get("mode", "merge")
        conflict = body.get("conflict", "replace")
        include_payload_files = bool(body.get("include_payload_files", True))

    if not isinstance(backup, dict) or backup.get("version") != 1:
        raise HTTPException(400, "Invalid or missing backup data")
    if mode not in ("merge", "replace"):
        raise HTTPException(400, "mode must be 'merge' or 'replace'")

    result = restore_backup_selective(backup, sections, mode, conflict)
    if include_payload_files and "payloads" in sections and payloads:
        result["payloads_restored"] = restore_backup_payloads(payloads)
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

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M")
    filename = f"ps5-autopayload-log-{stamp}.{ext}"
    return Response(
        content=content,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
