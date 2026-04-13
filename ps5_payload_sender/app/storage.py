"""
Persistent storage helpers:
  - one-time migration from legacy /data/ location
  - load/save devices and UI state
  - list available payloads and profiles
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from config import (
    ALLOWED_PAYLOAD_EXTENSIONS,
    CONFIG_BASE,
    DEVICES_FILE,
    HIDDEN_PROFILES,
    OLD_DEVICES_FILE,
    OLD_PAYLOAD_DIR,
    OLD_STATE_FILE,
    PAYLOAD_DIR,
    PROFILES_DIR,
    STATE_FILE,
)
from ha_component import write_custom_component
from payload_sender import resolve_port

_log = logging.getLogger("ps5_autopayload")


# ── Startup setup ─────────────────────────────────────────────────

def setup_storage() -> None:
    """Create directories, migrate legacy data, write HA custom component."""
    CONFIG_BASE.mkdir(parents=True, exist_ok=True)
    PAYLOAD_DIR.mkdir(exist_ok=True)
    PROFILES_DIR.mkdir(exist_ok=True)

    # One-time migration from /data/payloads/
    if OLD_PAYLOAD_DIR.exists():
        for f in OLD_PAYLOAD_DIR.iterdir():
            if not f.is_file():
                continue
            ext = f.suffix.lower()
            if ext in {".lua", ".elf"}:
                dest = PAYLOAD_DIR / f.name
            elif ext == ".txt":
                dest = PROFILES_DIR / f.name
            else:
                continue
            if not dest.exists():
                dest.write_bytes(f.read_bytes())

    # One-time migration of state / devices files
    if OLD_STATE_FILE.exists() and not STATE_FILE.exists():
        STATE_FILE.write_bytes(OLD_STATE_FILE.read_bytes())
    if OLD_DEVICES_FILE.exists() and not DEVICES_FILE.exists():
        DEVICES_FILE.write_bytes(OLD_DEVICES_FILE.read_bytes())

    # Remove legacy default profiles that are now built-in
    for name in ("ftp.txt", "goldhen.txt"):
        for d in (PAYLOAD_DIR, PROFILES_DIR):
            p = d / name
            if p.exists():
                p.unlink()

    write_custom_component()


# ── Devices ───────────────────────────────────────────────────────

def load_devices() -> List[Dict[str, Any]]:
    try:
        if DEVICES_FILE.exists():
            return json.loads(DEVICES_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def save_devices(devices: List[Dict[str, Any]]) -> None:
    DEVICES_FILE.write_text(
        json.dumps(devices, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── UI state ──────────────────────────────────────────────────────

def load_ui_state() -> dict:
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_ui_state(data: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Directory listings ────────────────────────────────────────────

def list_payloads() -> List[dict]:
    result = []
    for f in sorted(PAYLOAD_DIR.iterdir()):
        if f.is_file() and f.suffix.lower() in ALLOWED_PAYLOAD_EXTENSIONS:
            st = f.stat()
            result.append({
                "name": f.name,
                "size": st.st_size,
                "ext": f.suffix.lower(),
                "auto_port": resolve_port(f.name),
                "mtime": int(st.st_mtime),
            })
    return result


def list_profiles() -> List[str]:
    return [
        f.name for f in sorted(PROFILES_DIR.iterdir())
        if f.is_file() and f.suffix.lower() == ".txt" and f.name not in HIDDEN_PROFILES
    ]
