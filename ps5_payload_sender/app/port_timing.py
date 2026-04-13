"""
Port timing analysis – records how long each port takes to become reachable.

Storage format (TIMING_FILE):
  { "9026": [{"start": ISO, "ready": ISO, "duration_ms": int}, ...], ... }

Max MAX_TIMING_ENTRIES entries per port (oldest dropped).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from config import MAX_TIMING_ENTRIES, TIMING_FILE

_log = logging.getLogger("ps5_autopayload")


# ── I/O ───────────────────────────────────────────────────────────

def _load() -> Dict[str, List[dict]]:
    try:
        if TIMING_FILE.exists():
            return json.loads(TIMING_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save(data: Dict[str, List[dict]]) -> None:
    TIMING_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Public API ────────────────────────────────────────────────────

def record(port: int, duration_ms: int, start_iso: str = "", ready_iso: str = "") -> None:
    """Append a timing entry for *port*; prune to MAX_TIMING_ENTRIES."""
    data = _load()
    key = str(port)
    entries = data.get(key, [])
    entries.append({
        "start": start_iso or datetime.now(timezone.utc).isoformat(),
        "ready": ready_iso or datetime.now(timezone.utc).isoformat(),
        "duration_ms": duration_ms,
    })
    data[key] = entries[-MAX_TIMING_ENTRIES:]   # keep newest
    _save(data)
    _log.debug("Timing recorded – port %s: %d ms", port, duration_ms)


def get_stats() -> Dict[str, Any]:
    """Return stats for every tracked port."""
    data = _load()
    result: Dict[str, Any] = {}
    for port_str, entries in data.items():
        if not entries:
            continue
        durations = [e["duration_ms"] for e in entries]
        result[port_str] = {
            "port": int(port_str),
            "count": len(entries),
            "avg_ms": round(sum(durations) / len(durations)),
            "last_ms": durations[-1],
            "min_ms": min(durations),
            "max_ms": max(durations),
            "entries": entries,
        }
    return result


def get_port_stats(port: int) -> Dict[str, Any]:
    """Return stats for a single port (empty dict if no data)."""
    return get_stats().get(str(port), {})


def clear() -> None:
    """Delete all timing data."""
    if TIMING_FILE.exists():
        TIMING_FILE.unlink()
