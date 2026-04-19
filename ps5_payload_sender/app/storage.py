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
    FLOW_RUNS_FILE,
    HIDDEN_PROFILES,
    MAX_PAYLOAD_VERSIONS,
    OLD_DEVICES_FILE,
    OLD_PAYLOAD_DIR,
    OLD_STATE_FILE,
    PAYLOAD_DIR,
    PAYLOAD_META_FILE,
    PROFILES_DIR,
    SOURCES_FILE,
    STATE_FILE,
    TIMING_FILE,
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
    for name in ("ftp.txt", "goldhen.txt", "autoload.txt"):
        for d in (OLD_PAYLOAD_DIR, PAYLOAD_DIR, PROFILES_DIR):
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

# ── Sources ───────────────────────────────────────────────────────

def load_sources() -> List[Dict[str, Any]]:
    try:
        if SOURCES_FILE.exists():
            return json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def save_sources(sources: List[Dict[str, Any]]) -> None:
    SOURCES_FILE.write_text(
        json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Payload metadata ──────────────────────────────────────────────

def load_payload_meta() -> Dict[str, Any]:
    try:
        if PAYLOAD_META_FILE.exists():
            return json.loads(PAYLOAD_META_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_payload_meta(meta: Dict[str, Any]) -> None:
    PAYLOAD_META_FILE.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Directory listings ────────────────────────────────────────────

def list_payloads() -> List[dict]:
    meta = load_payload_meta()
    result = []
    for f in sorted(PAYLOAD_DIR.iterdir()):
        if f.is_file() and f.suffix.lower() in ALLOWED_PAYLOAD_EXTENSIONS:
            st = f.stat()
            entry: Dict[str, Any] = {
                "name": f.name,
                "size": st.st_size,
                "ext": f.suffix.lower(),
                "auto_port": resolve_port(f.name),
                "mtime": int(st.st_mtime),
            }
            if f.name in meta:
                src = dict(meta[f.name])
                versions = src.get("versions") or []
                src["latest_version"] = versions[0]["tag"] if versions else src.get("version", "")
                entry["source"] = src
            result.append(entry)
    return result


def list_profiles() -> List[str]:
    return [
        f.name for f in sorted(PROFILES_DIR.iterdir())
        if f.is_file() and f.suffix.lower() == ".txt" and f.name not in HIDDEN_PROFILES
    ]


# ── Version helpers ───────────────────────────────────────────────

def sort_versions(versions: list) -> list:
    """Stable-sort versions: stable releases → beta → alpha/test."""
    def _tier(v: dict) -> int:
        tag = v.get("tag", "").lower()
        if "alpha" in tag or "test" in tag:
            return 2
        if "beta" in tag:
            return 1
        return 0
    return sorted(versions, key=_tier)


def trim_versions(versions: list) -> list:
    """Keep only the newest MAX_PAYLOAD_VERSIONS entries."""
    return versions[:MAX_PAYLOAD_VERSIONS]


# ── Config backup / restore ───────────────────────────────────────

def build_backup() -> dict:
    """Collect full configuration into a single serialisable dict."""
    profiles: Dict[str, str] = {}
    if PROFILES_DIR.exists():
        for p in PROFILES_DIR.iterdir():
            if p.is_file() and p.suffix.lower() == ".txt" and p.name not in HIDDEN_PROFILES:
                profiles[p.name] = p.read_text(encoding="utf-8", errors="replace")

    return {
        "version": 1,
        "state":        load_ui_state(),
        "devices":      load_devices(),
        "sources":      load_sources(),
        "payload_meta": load_payload_meta(),
        "profiles":     profiles,
    }


def restore_backup(data: dict) -> None:
    """Restore all configuration from a backup dict (after auto-saving current)."""
    # Auto-backup current config first
    _auto_backup = CONFIG_BASE / "pre_restore_backup.json"
    _auto_backup.write_text(
        json.dumps(build_backup(), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if "state" in data:
        save_ui_state(data["state"])
    if "devices" in data:
        save_devices(data["devices"])
    if "sources" in data:
        save_sources(data["sources"])
    if "payload_meta" in data:
        save_payload_meta(data["payload_meta"])
    if "profiles" in data:
        PROFILES_DIR.mkdir(exist_ok=True)
        for name, content in data["profiles"].items():
            safe = Path(name).name
            if safe.endswith(".txt"):
                (PROFILES_DIR / safe).write_text(content, encoding="utf-8")


_SETTINGS_KEYS = frozenset({
    "ps5_ip", "advanced_mode", "favorites", "payload_favorites", "payload_filter",
})
_FLOW_KEYS = frozenset({"builder_steps", "builder_profile_name"})


def restore_backup_selective(
    data: dict,
    sections: list,
    mode: str = "merge",
    conflict: str = "replace",
) -> dict:
    """Selective restore with merge/replace and conflict handling.

    sections: any subset of ["sources", "payloads", "flows", "profiles", "settings"]
    mode:     "merge"   – keep existing entries, add new ones
              "replace" – overwrite the entire selected section
    conflict: "replace" – overwrite on duplicate key / filename (default)
              "skip"    – keep existing entry on collision (merge mode only)
    """
    import time as _time

    # Auto-backup current config before touching anything
    _auto = CONFIG_BASE / f"pre_import_backup_{int(_time.time())}.json"
    _auto.write_text(
        json.dumps(build_backup(), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    imported: dict = {
        "sources": 0, "payloads": 0, "flows": 0, "profiles": 0, "settings": False,
    }
    broken_profiles: list = []

    # Collect all state changes in one pass so flows + settings don't clobber each other
    state_changes: dict = {}
    need_state_write = False

    # ── Sources ───────────────────────────────────────────────────────
    if "sources" in sections and "sources" in data:
        incoming = data["sources"] or []
        if mode == "replace":
            save_sources(incoming)
        else:
            existing = load_sources()
            seen = {s.get("url") for s in existing}
            for s in incoming:
                if s.get("url") not in seen:
                    existing.append(s)
                    seen.add(s.get("url"))
            save_sources(existing)
        imported["sources"] = len(incoming)

    # ── Payload metadata ──────────────────────────────────────────────
    if "payloads" in sections and "payload_meta" in data:
        incoming = data["payload_meta"] or {}
        if mode == "replace":
            save_payload_meta(incoming)
        else:
            existing = load_payload_meta()
            for name, meta in incoming.items():
                if name not in existing or conflict == "replace":
                    existing[name] = meta
            save_payload_meta(existing)
        imported["payloads"] = len(incoming)

    # ── Auto-Load Builder flows (builder_steps inside state) ──────────
    if "flows" in sections and "state" in data:
        src = data["state"] or {}
        for k in _FLOW_KEYS:
            if k in src:
                state_changes[k] = src[k]
        imported["flows"] = len((data["state"] or {}).get("builder_steps") or [])
        need_state_write = True

    # ── Settings (ps5_ip / favorites / etc. + devices) ────────────────
    if "settings" in sections:
        if "state" in data:
            src = data["state"] or {}
            for k in _SETTINGS_KEYS:
                if k in src:
                    state_changes[k] = src[k]
            need_state_write = True
        if "devices" in data:
            incoming_devs = data["devices"] or []
            if mode == "replace":
                save_devices(incoming_devs)
            else:
                existing = load_devices()
                seen_ips = {d.get("ip") for d in existing}
                for d in incoming_devs:
                    if d.get("ip") not in seen_ips:
                        existing.append(d)
                        seen_ips.add(d.get("ip"))
                save_devices(existing)
        imported["settings"] = True

    # Write batched state changes once
    if need_state_write and state_changes:
        base = load_ui_state() if mode == "merge" else {}
        base.update(state_changes)
        save_ui_state(base)

    # ── Profiles (.txt files) ─────────────────────────────────────────
    if "profiles" in sections and "profiles" in data:
        PROFILES_DIR.mkdir(exist_ok=True)
        try:
            payload_names = {f.name for f in PAYLOAD_DIR.iterdir() if f.is_file()}
        except Exception:
            payload_names = set()

        count = 0
        for name, content in (data["profiles"] or {}).items():
            safe = Path(name).name
            if not safe.endswith(".txt"):
                continue
            target = PROFILES_DIR / safe
            if target.exists() and mode == "merge" and conflict == "skip":
                continue
            target.write_text(content, encoding="utf-8")
            count += 1
            # Validate: flag profiles that reference payload files not on disk
            for line in content.splitlines():
                stripped = line.strip()
                if (not stripped or stripped.startswith("#")
                        or stripped.startswith("?") or stripped.startswith("!")):
                    continue
                fname = stripped.split()[0]
                if fname and fname not in payload_names and safe not in broken_profiles:
                    broken_profiles.append(safe)
        imported["profiles"] = count

    _log.info(
        "Selective import: sections=%s mode=%s conflict=%s imported=%s broken=%s",
        sections, mode, conflict, imported, broken_profiles,
    )
    return {"imported": imported, "broken_profiles": broken_profiles}


def reset_config() -> dict:
    """Factory reset: back up then wipe all user data."""
    import time as _time

    # Backup first
    backup_file = CONFIG_BASE / f"backup_pre_reset_{int(_time.time())}.json"
    backup_file.write_text(
        json.dumps(build_backup(), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Wipe payload files
    deleted_payloads = 0
    if PAYLOAD_DIR.exists():
        for f in PAYLOAD_DIR.iterdir():
            if f.is_file():
                f.unlink()
                deleted_payloads += 1

    # Wipe profile .txt files
    deleted_profiles = 0
    if PROFILES_DIR.exists():
        for f in PROFILES_DIR.iterdir():
            if f.is_file() and f.suffix.lower() == ".txt":
                f.unlink()
                deleted_profiles += 1

    # Wipe config JSON files
    for cfg_f in (SOURCES_FILE, STATE_FILE, DEVICES_FILE,
                  PAYLOAD_META_FILE, TIMING_FILE, FLOW_RUNS_FILE):
        if cfg_f.exists():
            cfg_f.unlink()

    _log.info(
        "Config reset: %d payloads, %d profiles wiped; backup → %s",
        deleted_payloads, deleted_profiles, backup_file.name,
    )
    return {
        "success": True,
        "backup": backup_file.name,
        "deleted_payloads": deleted_payloads,
        "deleted_profiles": deleted_profiles,
    }
