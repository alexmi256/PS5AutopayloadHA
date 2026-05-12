"""
Flow run storage for timeline / multi-run analysis.

Storage format (flow_runs.json):
  [ { id, started_at, total_ms, safe_mode, steps: [...] }, ... ]

Step shapes
  { type:"wait_port", port, reached, duration_ms, offset_s }
  { type:"delay",     ms, duration_ms, offset_s }
  { type:"payload",   filename, port, safe_mode, success, duration_ms, offset_s }
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from atomic_write import atomic_write_text
from config import FLOW_RUNS_FILE, MAX_FLOW_RUNS


def _load() -> List[Dict[str, Any]]:
    try:
        return json.loads(FLOW_RUNS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(runs: list) -> None:
    FLOW_RUNS_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(FLOW_RUNS_FILE, json.dumps(runs, indent=2))


def record_run(run: Dict[str, Any]) -> None:
    runs = _load()
    runs.insert(0, run)
    _save(runs[:MAX_FLOW_RUNS])


def get_runs() -> List[Dict[str, Any]]:
    return _load()


def clear_runs() -> None:
    if FLOW_RUNS_FILE.exists():
        FLOW_RUNS_FILE.unlink()


def get_stats() -> Dict[str, Any]:
    """
    Aggregate port-wait stats across all stored runs.
    Returns { runs_count, port_stats: {port: {avg_ms, last_ms, min_ms, max_ms, count}} }
    """
    runs = _load()
    port_durations: Dict[str, List[int]] = {}

    for run in runs:
        for step in run.get("steps", []):
            if step.get("type") == "wait_port" and step.get("reached") and step.get("duration_ms") is not None:
                key = str(step["port"])
                port_durations.setdefault(key, []).append(step["duration_ms"])

    port_stats: Dict[str, Any] = {}
    for port_str, durations in port_durations.items():
        port_stats[port_str] = {
            "port":    int(port_str),
            "avg_ms":  int(sum(durations) / len(durations)),
            "last_ms": durations[0],        # list is newest-first
            "min_ms":  min(durations),
            "max_ms":  max(durations),
            "count":   len(durations),
        }

    return {
        "runs_count": len(runs),
        "port_stats": port_stats,
        "last_run":   runs[0] if runs else None,
    }
