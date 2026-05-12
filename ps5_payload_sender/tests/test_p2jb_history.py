"""Tests for p2jb_history storage + monitor-side recording hooks."""
from __future__ import annotations

import asyncio
import time

import pytest

import exec_engine
import p2jb_history
import p2jb_monitor
from models import P2JBMonitorConfig


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_monitor_state():
    p2jb_monitor._state = p2jb_monitor.MonitorState.IDLE
    p2jb_monitor._task = None
    p2jb_monitor._config = None
    p2jb_monitor._started_at = None
    p2jb_monitor._started_at_wall = None
    p2jb_monitor._last_check_at = None
    p2jb_monitor._loader_ready_at = None
    p2jb_monitor._last_error = None
    p2jb_monitor._recorded_this_run = False
    p2jb_monitor._lock = asyncio.Lock()
    exec_engine._exec_state = exec_engine.ExecState.IDLE
    yield


@pytest.fixture
def fake_port(monkeypatch):
    state = {"plan": False}

    async def _check(host, port, timeout=2.0):
        plan = state["plan"]
        if isinstance(plan, list):
            return plan.pop(0) if plan else False
        return bool(plan)

    monkeypatch.setattr(p2jb_monitor, "check_port", _check)

    class _Setter:
        def set(self, plan):
            state["plan"] = plan
    return _Setter()


@pytest.fixture(autouse=True)
def _silence_notifier(monkeypatch):
    monkeypatch.setattr(p2jb_monitor, "send_monitor_notification",
                        lambda *a, **k: {"persistent": True, "service": None})


# ── Storage ──────────────────────────────────────────────────────


def test_record_run_caps_at_max(tmp_p2jb_history_file, monkeypatch):
    monkeypatch.setattr(p2jb_history, "MAX_P2JB_HISTORY", 5)
    for i in range(8):
        p2jb_history.record_run(
            started_at=1700000000 + i,
            waited_s=10 + i,
            host="10.0.0.1",
            elf_port=9021,
            flow_name=f"flow_{i}",
            result="completed",
            auto_run=True,
        )
    runs = p2jb_history.get_runs()
    assert len(runs) == 5
    # newest-first
    assert runs[0]["flow_name"] == "flow_7"
    assert runs[-1]["flow_name"] == "flow_3"


def test_record_run_entry_shape(tmp_p2jb_history_file):
    p2jb_history.record_run(
        started_at=1700000000,
        waited_s=125.4,
        host="192.168.1.10",
        ps5_name="My PS5",
        elf_port=9021,
        flow_name="auto",
        result="failed",
        error="boom",
        auto_run=True,
    )
    run = p2jb_history.get_runs()[0]
    assert run["host"]      == "192.168.1.10"
    assert run["ps5_name"]  == "My PS5"
    assert run["elf_port"]  == 9021
    assert run["flow_name"] == "auto"
    assert run["result"]    == "failed"
    assert run["error"]     == "boom"
    assert run["auto_run"]  is True
    assert run["waited_s"]  == 125.4
    assert "ended_at" in run


def test_clear_runs_removes_file(tmp_p2jb_history_file):
    p2jb_history.record_run(
        started_at=time.time(), waited_s=1, host="x",
        elf_port=9021, flow_name=None, result="stopped",
    )
    assert p2jb_history.get_runs()
    p2jb_history.clear_runs()
    assert p2jb_history.get_runs() == []


def test_lookup_ps5_name(tmp_p2jb_history_file, monkeypatch):
    monkeypatch.setattr(p2jb_history, "load_devices",
                        lambda: [{"name": "Bedroom", "ip": "192.168.1.42"}],
                        raising=False)
    # Patch the dynamic import inside lookup_ps5_name
    import storage
    monkeypatch.setattr(storage, "load_devices",
                        lambda: [{"name": "Bedroom", "ip": "192.168.1.42"}])
    assert p2jb_history.lookup_ps5_name("192.168.1.42") == "Bedroom"
    assert p2jb_history.lookup_ps5_name("10.0.0.1") == ""


# ── Monitor → history integration ────────────────────────────────


def test_history_recorded_on_loader_ready_no_autorun(fake_port, tmp_p2jb_history_file):
    fake_port.set(True)
    cfg = P2JBMonitorConfig(
        host="10.0.0.5", check_interval=1, max_wait=5,
        auto_run=False, notify_loader_ready=False,
    )

    async def scenario():
        await p2jb_monitor.start_monitor(cfg)
        await asyncio.wait_for(p2jb_monitor._task, timeout=2)

    asyncio.run(scenario())
    runs = p2jb_history.get_runs()
    assert len(runs) == 1
    assert runs[0]["result"]   == "loader_ready"
    assert runs[0]["host"]     == "10.0.0.5"
    assert runs[0]["auto_run"] is False


def test_history_recorded_on_timeout(fake_port, tmp_p2jb_history_file):
    fake_port.set(False)
    cfg = P2JBMonitorConfig(
        host="10.0.0.5", check_interval=1, max_wait=1,
        auto_run=False, notify_flow_failed=False,
    )

    async def scenario():
        await p2jb_monitor.start_monitor(cfg)
        await asyncio.wait_for(p2jb_monitor._task, timeout=3)

    asyncio.run(scenario())
    runs = p2jb_history.get_runs()
    assert len(runs) == 1
    assert runs[0]["result"] == "timeout"
    assert runs[0]["error"]


def test_history_recorded_on_stop(fake_port, tmp_p2jb_history_file):
    fake_port.set(False)
    cfg = P2JBMonitorConfig(host="10.0.0.5", check_interval=30, max_wait=300)

    async def scenario():
        await p2jb_monitor.start_monitor(cfg)
        await asyncio.sleep(0.05)
        await p2jb_monitor.stop_monitor()

    asyncio.run(scenario())
    runs = p2jb_history.get_runs()
    assert len(runs) == 1
    assert runs[0]["result"] == "stopped"


def test_history_recorded_once_per_run(fake_port, tmp_p2jb_history_file):
    """Ensure stop() after a terminal state doesn't double-record."""
    fake_port.set(True)
    cfg = P2JBMonitorConfig(
        host="10.0.0.5", check_interval=1, max_wait=5,
        auto_run=False, notify_loader_ready=False,
    )

    async def scenario():
        await p2jb_monitor.start_monitor(cfg)
        await asyncio.wait_for(p2jb_monitor._task, timeout=2)
        # Now call stop — would have double-recorded without the guard
        await p2jb_monitor.stop_monitor()

    asyncio.run(scenario())
    assert len(p2jb_history.get_runs()) == 1


# ── Test-notification endpoint helpers ───────────────────────────


def test_test_notification_rejects_unknown_event(tmp_p2jb_history_file):
    async def scenario():
        with pytest.raises(ValueError):
            await p2jb_monitor.test_notification(
                "bogus", notify_service=None, host="h", elf_port=1, flow_name=None,
            )
    asyncio.run(scenario())


def test_test_notification_returns_success(tmp_p2jb_history_file):
    async def scenario():
        return await p2jb_monitor.test_notification(
            "loader_ready", notify_service=None,
            host="10.0.0.5", elf_port=9021, flow_name=None,
        )
    r = asyncio.run(scenario())
    assert r["success"] is True
    assert r["event"]   == "loader_ready"
    assert r["title"].endswith("(test)")
    # No history written by a pure notification test
    assert p2jb_history.get_runs() == []


def test_test_notification_reports_failure_when_service_unreachable(monkeypatch):
    """If notify.<service> fails, result.service is False → overall success=False."""
    monkeypatch.setattr(
        p2jb_monitor, "send_monitor_notification",
        lambda *a, **k: {"persistent": True, "service": False},
    )

    async def scenario():
        return await p2jb_monitor.test_notification(
            "flow_failed", notify_service="mobile_app_iphone",
            host="10.0.0.5", elf_port=9021, flow_name="P2JB",
        )
    r = asyncio.run(scenario())
    assert r["success"] is False
    assert r["error"]


# ── Simulate loader ready ────────────────────────────────────────


def test_simulate_loader_ready_does_not_run_flow_by_default(monkeypatch, tmp_p2jb_history_file):
    flow_called = {"n": 0}

    async def _fake_run(req):
        flow_called["n"] += 1
        return {"success": True, "steps": 1}
    monkeypatch.setattr(p2jb_monitor, "run_autoload", _fake_run)

    cfg = P2JBMonitorConfig(host="10.0.0.5", flow_name="my_flow")

    async def scenario():
        return await p2jb_monitor.simulate_loader_ready(cfg, run_real_flow=False)

    r = asyncio.run(scenario())
    assert r["success"] is True
    assert r["ran_flow"] is False
    assert flow_called["n"] == 0


def test_simulate_loader_ready_runs_flow_when_requested(monkeypatch, tmp_p2jb_history_file):
    async def _fake_run(req):
        return {"success": True, "steps": 3, "message": "ok"}
    monkeypatch.setattr(p2jb_monitor, "run_autoload", _fake_run)

    cfg = P2JBMonitorConfig(
        host="10.0.0.5", flow_name="my_flow",
        notify_flow_completed=True, notify_flow_started=True,
    )

    async def scenario():
        return await p2jb_monitor.simulate_loader_ready(cfg, run_real_flow=True)

    r = asyncio.run(scenario())
    assert r["success"] is True
    assert r["ran_flow"] is True
    assert r["event"] == "flow_completed"


def test_simulate_loader_ready_requires_flow_for_real_run():
    cfg = P2JBMonitorConfig(host="10.0.0.5", flow_name=None)

    async def scenario():
        with pytest.raises(ValueError, match="flow_name"):
            await p2jb_monitor.simulate_loader_ready(cfg, run_real_flow=True)

    asyncio.run(scenario())


def test_simulate_loader_ready_blocks_if_builder_busy():
    exec_engine._exec_state = exec_engine.ExecState.RUNNING
    cfg = P2JBMonitorConfig(host="10.0.0.5", flow_name="x")

    async def scenario():
        with pytest.raises(RuntimeError, match="builder flow"):
            await p2jb_monitor.simulate_loader_ready(cfg, run_real_flow=True)

    asyncio.run(scenario())
