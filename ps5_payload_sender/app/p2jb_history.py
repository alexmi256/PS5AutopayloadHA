"""
Persistent history of P2JB / Patience monitor runs.

Storage format (p2jb_history.json):
  [ { started_at, ended_at, waited_s, host, ps5_name, elf_port,
      flow_name, result, error, auto_run }, ...]   # newest-first

`result` is one of: completed | loader_ready | failed | timeout | stopped.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from atomic_write import atomic_write_text
from config import MAX_P2JB_HISTORY, P2JB_HISTORY_FILE


def _load() -> List[Dict[str, Any]]:
    try:
        return json.loads(P2JB_HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(runs: List[Dict[str, Any]]) -> None:
    P2JB_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(P2JB_HISTORY_FILE, json.dumps(runs, indent=2))


def record_run(
    *,
    started_at: float,
    waited_s: float,
    host: str,
    elf_port: int,
    flow_name: Optional[str],
    result: str,
    error: Optional[str] = None,
    auto_run: bool = False,
    ps5_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Append a new history entry (newest-first), trimming to MAX_P2JB_HISTORY."""
    entry: Dict[str, Any] = {
        "started_at": started_at,
        "ended_at":   time.time(),
        "waited_s":   round(float(waited_s), 1),
        "host":       host,
        "ps5_name":   ps5_name or "",
        "elf_port":   elf_port,
        "flow_name":  flow_name or "",
        "result":     result,
        "error":      error or "",
        "auto_run":   bool(auto_run),
    }
    runs = _load()
    runs.insert(0, entry)
    _save(runs[:MAX_P2JB_HISTORY])
    return entry


def get_runs() -> List[Dict[str, Any]]:
    return _load()


def clear_runs() -> None:
    if P2JB_HISTORY_FILE.exists():
        P2JB_HISTORY_FILE.unlink()


def lookup_ps5_name(host: str) -> str:
    """Resolve a configured device name for *host*, if any."""
    try:
        from storage import load_devices
        for dev in load_devices():
            if (dev.get("ip") or "").strip() == host.strip():
                return dev.get("name") or ""
    except Exception:
        pass
    return ""
