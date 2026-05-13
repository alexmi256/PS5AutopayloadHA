"""
Persistent history of executed flow profiles.

Stores up to :data:`config.MAX_FLOW_HISTORY` recent runs in
``/config/ps5_autopayload/flow_history.json``. The file is wiped by
:func:`storage.full_config_reset` along with the other JSON config
artefacts.

Storage shape (newest-first):
  [
    {
      "started_at": 1714000000,   # unix seconds
      "ended_at":   1714002820,
      "waited_s":   1820.0,       # *total* wall time spent in the run
      "loader_waited_s": 1740.0,  # time inside the wait_for_loader step (or null)
      "host":       "192.168.1.5",
      "ps5_name":   "Living Room",
      "loader_port": 9021,        # captured from the wait_for_loader step
      "flow_name":  "P2JB Autoload",
      "result":     "completed",  # completed | loader_ready | failed_timeout
                                  # | failed | stopped
      "error":      "",
      "steps":      4
    },
    ...
  ]
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from atomic_write import atomic_write_text
from config import FLOW_HISTORY_FILE, MAX_FLOW_HISTORY


def _load() -> List[Dict[str, Any]]:
    try:
        return json.loads(FLOW_HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(runs: List[Dict[str, Any]]) -> None:
    FLOW_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(FLOW_HISTORY_FILE, json.dumps(runs, indent=2))


def record_run(
    *,
    started_at: float,
    waited_s: float,
    host: str,
    flow_name: str,
    result: str,
    loader_port: Optional[int] = None,
    loader_waited_s: Optional[float] = None,
    error: Optional[str] = None,
    steps: int = 0,
    ps5_name: Optional[str] = None,
) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "started_at":      started_at,
        "ended_at":        time.time(),
        "waited_s":        round(float(waited_s), 1),
        "loader_waited_s": None if loader_waited_s is None else round(float(loader_waited_s), 1),
        "host":            host,
        "ps5_name":        ps5_name or "",
        "loader_port":     loader_port,
        "flow_name":       flow_name,
        "result":          result,
        "error":           error or "",
        "steps":           steps,
    }
    runs = _load()
    runs.insert(0, entry)
    _save(runs[:MAX_FLOW_HISTORY])
    return entry


def get_runs() -> List[Dict[str, Any]]:
    return _load()


def clear_runs() -> None:
    if FLOW_HISTORY_FILE.exists():
        FLOW_HISTORY_FILE.unlink()


def lookup_ps5_name(host: str) -> str:
    """Resolve a configured device name for *host*, if any."""
    try:
        from storage import load_devices
        for dev in load_devices():
            if (dev.get("ip") or "").strip() == (host or "").strip():
                return dev.get("name") or ""
    except Exception:
        pass
    return ""
