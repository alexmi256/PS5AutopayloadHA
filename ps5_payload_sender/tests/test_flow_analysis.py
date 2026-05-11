"""Tests for flow_analysis run storage and aggregate stats."""
from __future__ import annotations

import flow_analysis


def _make_run(run_id: int, port_steps: list[tuple[int, int, bool]]) -> dict:
    """Build a minimal run record with wait_port steps."""
    return {
        "id": run_id,
        "started_at": float(run_id),
        "total_ms": 0,
        "safe_mode": False,
        "steps": [
            {"type": "wait_port", "port": port, "duration_ms": dur, "reached": reached}
            for port, dur, reached in port_steps
        ],
    }


def test_record_and_get_runs_newest_first(tmp_flow_runs_file):
    flow_analysis.record_run(_make_run(1, []))
    flow_analysis.record_run(_make_run(2, []))
    runs = flow_analysis.get_runs()
    assert [r["id"] for r in runs] == [2, 1]


def test_record_run_prunes_to_max(tmp_flow_runs_file, monkeypatch):
    monkeypatch.setattr(flow_analysis, "MAX_FLOW_RUNS", 3)
    for i in range(5):
        flow_analysis.record_run(_make_run(i, []))
    runs = flow_analysis.get_runs()
    assert [r["id"] for r in runs] == [4, 3, 2]


def test_clear_runs(tmp_flow_runs_file):
    flow_analysis.record_run(_make_run(1, []))
    assert tmp_flow_runs_file.exists()
    flow_analysis.clear_runs()
    assert not tmp_flow_runs_file.exists()
    assert flow_analysis.get_runs() == []


def test_get_stats_aggregates_reached_wait_ports(tmp_flow_runs_file):
    flow_analysis.record_run(_make_run(1, [(9021, 1000, True), (9026, 500, True)]))
    flow_analysis.record_run(_make_run(2, [(9021, 2000, True), (9021, 9999, False)]))

    stats = flow_analysis.get_stats()
    assert stats["runs_count"] == 2
    assert stats["last_run"]["id"] == 2

    port_stats = stats["port_stats"]
    assert set(port_stats.keys()) == {"9021", "9026"}

    s9021 = port_stats["9021"]
    assert s9021["count"] == 2
    assert s9021["min_ms"] == 1000
    assert s9021["max_ms"] == 2000
    assert s9021["avg_ms"] == 1500
    # list is newest-first; last_ms means most recent
    assert s9021["last_ms"] == 2000


def test_get_stats_empty(tmp_flow_runs_file):
    stats = flow_analysis.get_stats()
    assert stats == {"runs_count": 0, "port_stats": {}, "last_run": None}


def test_get_stats_ignores_unreached_wait_ports(tmp_flow_runs_file):
    flow_analysis.record_run(_make_run(1, [(9021, 1234, False)]))
    stats = flow_analysis.get_stats()
    assert stats["port_stats"] == {}
