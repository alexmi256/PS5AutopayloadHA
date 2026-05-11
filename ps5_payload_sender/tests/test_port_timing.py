"""Tests for the port_timing storage and stats helpers."""
from __future__ import annotations

import port_timing


def test_record_and_get_stats(tmp_timing_file):
    port_timing.record(9021, 1500, "2026-01-01T00:00:00Z", "2026-01-01T00:00:01Z")
    port_timing.record(9021, 2500)
    port_timing.record(9026, 800)

    stats = port_timing.get_stats()
    assert set(stats.keys()) == {"9021", "9026"}

    s9021 = stats["9021"]
    assert s9021["port"] == 9021
    assert s9021["count"] == 2
    assert s9021["min_ms"] == 1500
    assert s9021["max_ms"] == 2500
    assert s9021["avg_ms"] == 2000
    assert s9021["last_ms"] == 2500


def test_get_port_stats_for_missing_port_returns_empty(tmp_timing_file):
    assert port_timing.get_port_stats(9999) == {}


def test_record_prunes_to_max_entries(tmp_timing_file, monkeypatch):
    monkeypatch.setattr(port_timing, "MAX_TIMING_ENTRIES", 3)
    for i in range(5):
        port_timing.record(9021, (i + 1) * 100)
    stats = port_timing.get_port_stats(9021)
    assert stats["count"] == 3
    # Oldest two dropped → durations 300, 400, 500
    assert stats["min_ms"] == 300
    assert stats["max_ms"] == 500
    assert stats["last_ms"] == 500


def test_clear_removes_file(tmp_timing_file):
    port_timing.record(9021, 1000)
    assert tmp_timing_file.exists()
    port_timing.clear()
    assert not tmp_timing_file.exists()
    assert port_timing.get_stats() == {}


def test_load_returns_empty_when_file_missing(tmp_timing_file):
    assert not tmp_timing_file.exists()
    assert port_timing.get_stats() == {}
