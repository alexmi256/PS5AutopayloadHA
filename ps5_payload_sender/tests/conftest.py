"""Shared pytest fixtures.

`storage` writes under /config/ps5_autopayload at import time via
`setup_storage()` (called by main.py at startup). The tests do not need
that — they exercise pure parser / I/O helpers and redirect file paths
to tmp_path via monkeypatch.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


@pytest.fixture
def tmp_timing_file(tmp_path, monkeypatch):
    """Redirect port_timing's storage file to a fresh tmp file."""
    import port_timing
    f = tmp_path / "port_timing.json"
    monkeypatch.setattr(port_timing, "TIMING_FILE", f)
    return f


@pytest.fixture
def tmp_flow_runs_file(tmp_path, monkeypatch):
    """Redirect flow_analysis' storage file to a fresh tmp file."""
    import flow_analysis
    f = tmp_path / "flow_runs.json"
    monkeypatch.setattr(flow_analysis, "FLOW_RUNS_FILE", f)
    return f


@pytest.fixture
def tmp_p2jb_history_file(tmp_path, monkeypatch):
    """Redirect p2jb_history's storage file to a fresh tmp file."""
    import p2jb_history
    f = tmp_path / "p2jb_history.json"
    monkeypatch.setattr(p2jb_history, "P2JB_HISTORY_FILE", f)
    return f
