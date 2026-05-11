from __future__ import annotations

import asyncio
import hashlib
import shutil
from pathlib import Path

import aiofiles
from fastapi import APIRouter, File, HTTPException, UploadFile

from config import ALLOWED_PAYLOAD_EXTENSIONS, HIDDEN_PROFILES, PAYLOAD_DIR, PROFILES_DIR
from exec_engine import executor
from github_client import download_payload as gh_download_payload
from models import (
    ImportPayloadRequest,
    SendRequest,
    SetDefaultVersionRequest,
    SwitchVersionRequest,
)
from payload_sender import resolve_port, send_payload
from storage import (
    list_payloads,
    load_payload_meta,
    load_sources,
    save_payload_meta,
    sort_versions,
    trim_versions,
)
from websocket_manager import manager

router = APIRouter()


@router.get("/api/payloads")
async def api_list_payloads():
    return {"payloads": list_payloads()}


@router.post("/api/payloads/upload")
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


@router.delete("/api/payloads/{filename}")
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


@router.post("/api/payloads/import")
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
    payload_hash = hashlib.sha256(data).hexdigest()
    (PAYLOAD_DIR / safe).write_bytes(data)
    meta = load_payload_meta()
    existing = meta.get(safe, {})
    existing_versions = existing.get("versions", [])
    new_versions = req.all_versions or [{"tag": req.version, "download_url": req.download_url}]
    seen_tags: set = set()
    merged: list = []
    for v in (new_versions + existing_versions):
        if v["tag"] not in seen_tags:
            merged.append(v)
            seen_tags.add(v["tag"])
    sources = load_sources()
    src_entry = next((s for s in sources if s["repo"] == req.repo), {})
    display_name = src_entry.get("display_name", "")
    meta[safe] = {
        **existing,
        "repo": req.repo, "asset": req.asset_name,
        "version": req.version, "versions": trim_versions(sort_versions(merged)),
        "display_name":         display_name,
        "payload_hash":         payload_hash,
        "release_published_at": req.release_published_at,
        "asset_updated_at":     req.asset_updated_at,
        "asset_size":           req.asset_size,
        "release_id":           req.release_id,
    }
    save_payload_meta(meta)
    await manager.status(f"'{safe}' imported from {req.repo} {req.version}", level="success")
    return {"success": True, "filename": safe, "size": len(data), "auto_port": resolve_port(safe)}


@router.post("/api/payloads/{filename}/switch-version")
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


@router.post("/api/payloads/{filename}/set-default-version")
async def api_set_default_version(filename: str, req: SetDefaultVersionRequest):
    meta = load_payload_meta()
    safe = Path(filename).name
    if safe not in meta:
        raise HTTPException(404, "Payload not in metadata")
    meta[safe]["version"] = req.version
    save_payload_meta(meta)
    return {"ok": True, "version": req.version}


@router.post("/api/payloads/{filename}/rollback")
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


@router.get("/api/payloads/{filename}/usage")
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


@router.post("/api/send")
async def api_send(req: SendRequest):
    port = resolve_port(req.filename, req.port)
    await manager.status(f"Sending '{req.filename}' → {req.host}:{port} …")
    result = await send_payload(req.host, port, req.filename)
    await manager.status(result["message"], level="success" if result["success"] else "error")
    return result
