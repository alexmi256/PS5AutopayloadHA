"""Tests for the P2JB / Patience loader-ready monitor state machine.

Uses `asyncio.run()` per test instead of pytest-asyncio so it slots into
the existing requirement-free test suite. Each test reinitialises the
module-level state via the `_reset_monitor_state` fixture.
"""
from __future__ import annotations

import asyncio

import pytest

import exec_engine
import p2jb_monitor
from models import P2JBMonitorConfig


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_monitor_state():
    p2jb_monitor._state = p2jb_monitor.MonitorState.IDLE
    p2jb_monitor._task = None
    p2jb_monitor._config = None
    p2jb_monitor._started_at = None
    p2jb_monitor._last_check_at = None
    p2jb_monitor._loader_ready_at = None
    p2jb_monitor._last_error = None
    p2jb_monitor._lock = asyncio.Lock()
    exec_engine._exec_state = exec_engine.ExecState.IDLE
    yield


@pytest.fixture
def fake_port(monkeypatch):
    """Patch port_checker.check_port with a configurable async fake.

    Usage in tests:
        fake_port.set(True)                  # always reachable
        fake_port.set([False, False, True])  # reachable on 3rd poll
    """
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


@pytest.fixture
def fake_notifier(monkeypatch):
    """Capture every notification call instead of hitting HA."""
    sent = []

    def _send(title, message, service):
        sent.append({"title": title, "message": message, "service": service})
        return {"persistent": True, "service": True if service else None}

    monkeypatch.setattr(p2jb_monitor, "send_monitor_notification", _send)
    return sent


# ── Validation ───────────────────────────────────────────────────


def test_start_rejects_zero_interval(fake_port):
    cfg = P2JBMonitorConfig(host="1.2.3.4", check_interval=0.1)
    with pytest.raises(ValueError, match="check_interval"):
        asyncio.run(p2jb_monitor.start_monitor(cfg))


def test_start_rejects_max_wait_below_interval(fake_port):
    cfg = P2JBMonitorConfig(host="1.2.3.4", check_interval=30, max_wait=5)
    with pytest.raises(ValueError, match="max_wait"):
        asyncio.run(p2jb_monitor.start_monitor(cfg))


def test_start_rejects_auto_run_without_flow(fake_port):
    cfg = P2JBMonitorConfig(host="1.2.3.4", auto_run=True, flow_name=None)
    with pytest.raises(ValueError, match="flow_name"):
        asyncio.run(p2jb_monitor.start_monitor(cfg))


def test_start_blocks_when_builder_running(fake_port):
    exec_engine._exec_state = exec_engine.ExecState.RUNNING
    cfg = P2JBMonitorConfig(host="1.2.3.4", check_interval=1, max_wait=5)
    with pytest.raises(RuntimeError, match="builder flow"):
        asyncio.run(p2jb_monitor.start_monitor(cfg))


# ── State transitions ────────────────────────────────────────────


def test_loader_ready_terminal_when_auto_run_off(fake_port, fake_notifier):
    fake_port.set(True)
    cfg = P2JBMonitorConfig(
        host="1.2.3.4", check_interval=1, max_wait=5,
        auto_run=False, notify_loader_ready=True,
    )

    async def scenario():
        await p2jb_monitor.start_monitor(cfg)
        await asyncio.wait_for(p2jb_monitor._task, timeout=2)

    asyncio.run(scenario())
    assert p2jb_monitor._state == p2jb_monitor.MonitorState.LOADER_READY
    assert any("Loader is ready" in n["title"] for n in fake_notifier)


def test_timeout_when_port_never_reachable(fake_port, fake_notifier):
    fake_port.set(False)
    cfg = P2JBMonitorConfig(
        host="1.2.3.4", check_interval=1, max_wait=1,
        auto_run=False, notify_flow_failed=True,
    )

    async def scenario():
        await p2jb_monitor.start_monitor(cfg)
        await asyncio.wait_for(p2jb_monitor._task, timeout=3)

    asyncio.run(scenario())
    assert p2jb_monitor._state == p2jb_monitor.MonitorState.TIMEOUT
    assert any("timeout" in n["title"].lower() for n in fake_notifier)


def test_stop_transitions_to_stopped(fake_port):
    fake_port.set(False)
    cfg = P2JBMonitorConfig(host="1.2.3.4", check_interval=30, max_wait=300)

    async def scenario():
        await p2jb_monitor.start_monitor(cfg)
        await asyncio.sleep(0.05)
        return await p2jb_monitor.stop_monitor()

    status = asyncio.run(scenario())
    assert status["state"] == p2jb_monitor.MonitorState.STOPPED


def test_double_start_raises(fake_port):
    fake_port.set(False)
    cfg = P2JBMonitorConfig(host="1.2.3.4", check_interval=30, max_wait=300)

    async def scenario():
        await p2jb_monitor.start_monitor(cfg)
        try:
            with pytest.raises(RuntimeError, match="already running"):
                await p2jb_monitor.start_monitor(cfg)
        finally:
            await p2jb_monitor.stop_monitor()

    asyncio.run(scenario())


def test_auto_run_aborts_if_builder_starts(fake_port, fake_notifier, monkeypatch):
    """If exec_engine becomes busy between loader-ready and auto-run,
    the monitor must transition FAILED rather than silently waiting."""
    fake_port.set(True)

    async def _fake_run(req):
        return {"success": True, "steps": 0}
    monkeypatch.setattr(p2jb_monitor, "run_autoload", _fake_run)

    cfg = P2JBMonitorConfig(
        host="1.2.3.4", check_interval=1, max_wait=5,
        auto_run=True, flow_name="my_flow",
        notify_flow_failed=True,
    )

    # IDLE for start(), then RUNNING during _on_loader_ready
    monkeypatch.setattr(p2jb_monitor, "get_exec_state",
                        lambda: exec_engine.ExecState.IDLE)

    async def scenario():
        await p2jb_monitor.start_monitor(cfg)
        monkeypatch.setattr(p2jb_monitor, "get_exec_state",
                            lambda: exec_engine.ExecState.RUNNING)
        await asyncio.wait_for(p2jb_monitor._task, timeout=2)

    asyncio.run(scenario())
    assert p2jb_monitor._state == p2jb_monitor.MonitorState.FAILED


def test_no_notification_when_disabled(fake_port, fake_notifier):
    fake_port.set(True)
    cfg = P2JBMonitorConfig(
        host="1.2.3.4", check_interval=1, max_wait=5,
        auto_run=False, notify_loader_ready=False,
    )

    async def scenario():
        await p2jb_monitor.start_monitor(cfg)
        await asyncio.wait_for(p2jb_monitor._task, timeout=2)

    asyncio.run(scenario())
    assert p2jb_monitor._state == p2jb_monitor.MonitorState.LOADER_READY
    assert fake_notifier == []


# ── Duration formatter ───────────────────────────────────────────


def test_fmt_duration_handles_minutes():
    assert p2jb_monitor._fmt_duration(42)    == "42s"
    assert p2jb_monitor._fmt_duration(95)    == "1m 35s"
    assert p2jb_monitor._fmt_duration(3725)  == "1h 02m 05s"
