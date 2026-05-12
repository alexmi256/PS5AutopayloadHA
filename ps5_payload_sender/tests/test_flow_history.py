"""Tests for flow_history.py — high-level run storage capped at MAX_FLOW_HISTORY."""
from __future__ import annotations

import time

import pytest

import flow_history


@pytest.fixture
def tmp_history(tmp_path, monkeypatch):
    f = tmp_path / "flow_history.json"
    monkeypatch.setattr(flow_history, "FLOW_HISTORY_FILE", f)
    return f


def test_record_caps_at_max(tmp_history, monkeypatch):
    monkeypatch.setattr(flow_history, "MAX_FLOW_HISTORY", 4)
    for i in range(7):
        flow_history.record_run(
            started_at=1700000000 + i,
            waited_s=10 + i,
            host="10.0.0.1",
            flow_name=f"flow_{i}",
            result="completed",
        )
    runs = flow_history.get_runs()
    assert [r["flow_name"] for r in runs] == ["flow_6", "flow_5", "flow_4", "flow_3"]


def test_entry_shape(tmp_history):
    entry = flow_history.record_run(
        started_at=1700000000,
        waited_s=42.5,
        loader_waited_s=30.0,
        host="192.168.1.5",
        ps5_name="My PS5",
        loader_port=9021,
        flow_name="P2JB Autoload",
        result="failed_timeout",
        error="loader not found",
        steps=4,
    )
    for k in ("started_at", "ended_at", "waited_s", "loader_waited_s",
              "host", "ps5_name", "loader_port", "flow_name", "result",
              "error", "steps"):
        assert k in entry, f"missing key: {k}"
    assert entry["result"]   == "failed_timeout"
    assert entry["steps"]    == 4
    assert entry["waited_s"] == 42.5


def test_clear(tmp_history):
    flow_history.record_run(
        started_at=time.time(), waited_s=1, host="x",
        flow_name="x", result="stopped",
    )
    assert flow_history.get_runs()
    flow_history.clear_runs()
    assert flow_history.get_runs() == []


def test_lookup_ps5_name(tmp_history, monkeypatch):
    import storage
    monkeypatch.setattr(storage, "load_devices",
                        lambda: [{"name": "Bedroom", "ip": "192.168.1.42"}])
    assert flow_history.lookup_ps5_name("192.168.1.42") == "Bedroom"
    assert flow_history.lookup_ps5_name("10.0.0.1") == ""
