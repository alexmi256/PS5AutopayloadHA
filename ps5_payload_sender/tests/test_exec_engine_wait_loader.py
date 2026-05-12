"""Integration tests for the WAIT FOR LOADER directive inside run_autoload.

Patches all I/O surfaces so the tests are deterministic:
  * ``port_checker.check_port`` → configurable sequence
  * ``notifications`` dispatcher → recorder
  * ``send_payload`` → no-op success
  * Profile file → written into a tmp PROFILES_DIR
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import exec_engine
import flow_history
import notifications
from models import AutoloadRequest


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_exec_state():
    exec_engine._exec_state = exec_engine.ExecState.IDLE
    exec_engine._run_lock = asyncio.Lock()
    exec_engine._stop_event = asyncio.Event()
    exec_engine._pause_event = asyncio.Event()
    exec_engine._pause_event.set()
    yield


@pytest.fixture
def tmp_profile(tmp_path, monkeypatch):
    """Create a tmp profile directory and write a profile file into it."""
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    monkeypatch.setattr(exec_engine, "PROFILES_DIR", profiles)

    def _make(content: str, name: str = "test.txt") -> str:
        (profiles / name).write_text(content, encoding="utf-8")
        return name
    return _make


@pytest.fixture
def patched_io(monkeypatch):
    """Stub out network I/O + notifications, return a recorder."""
    rec = {"polls": [], "notifications": [], "payloads": []}

    async def _check_port(host, port, timeout=2.0):
        plan = rec.setdefault("port_plan", [])
        ok = plan.pop(0) if plan else False
        rec["polls"].append({"host": host, "port": port, "ok": ok})
        return ok

    async def _send_payload(host, port, filename):
        rec["payloads"].append({"host": host, "port": port, "filename": filename})
        return {"success": True, "message": "ok", "bytes_sent": 1}

    async def _fire(event, cfg, *, message="", service_override=None, title_suffix=""):
        rec["notifications"].append({
            "event": event, "msg": message, "service_override": service_override,
        })
        return {"event": event, "title": event, "persistent": True, "service": True}

    async def _fire_if_enabled(event, cfg, **kw):
        if not cfg.get(event):
            return None
        return await _fire(event, cfg, **kw)

    async def _fire_custom(title, msg, cfg, *, service_override=None):
        rec["notifications"].append({
            "event": "@notify", "title": title, "msg": msg,
            "service_override": service_override,
        })
        return {"title": title, "persistent": True}

    monkeypatch.setattr(exec_engine, "check_port", _check_port)
    monkeypatch.setattr(exec_engine, "send_payload", _send_payload)
    monkeypatch.setattr(notifications, "fire",            _fire)
    monkeypatch.setattr(notifications, "fire_if_enabled", _fire_if_enabled)
    monkeypatch.setattr(notifications, "fire_custom",     _fire_custom)
    # Also patch the symbols imported into exec_engine's namespace:
    monkeypatch.setattr(exec_engine.notifications, "fire",            _fire)
    monkeypatch.setattr(exec_engine.notifications, "fire_if_enabled", _fire_if_enabled)
    monkeypatch.setattr(exec_engine.notifications, "fire_custom",     _fire_custom)

    # Swallow ha_client push_ha_state — no Supervisor in tests
    monkeypatch.setattr(exec_engine, "push_ha_state", lambda *a, **k: None)
    return rec


@pytest.fixture
def tmp_history(tmp_path, monkeypatch):
    f = tmp_path / "flow_history.json"
    monkeypatch.setattr(flow_history, "FLOW_HISTORY_FILE", f)
    return f


# ── Tests ────────────────────────────────────────────────────────


def test_wait_for_loader_success_path(tmp_profile, patched_io, tmp_history, monkeypatch):
    """Loader becomes reachable on the 3rd poll → loader_ready notification
    fires, the next payload step runs, flow ends as 'completed' in history."""
    name = tmp_profile(
        '# ~notify loader_ready=on flow_completed=on\n'
        '??9021 60 1 1\n'             # max 60 s, poll 1 s, 1 sample
        'kpayload.elf\n'
    )
    # Reachable on the 3rd poll
    patched_io["port_plan"] = [False, False, True]

    async def scenario():
        return await exec_engine.run_autoload(AutoloadRequest(
            host="10.0.0.5", profile=name, continue_on_error=False,
        ))

    result = asyncio.run(scenario())
    assert result["success"] is True, result
    # loader_ready notification fired exactly once
    events = [n["event"] for n in patched_io["notifications"]]
    assert "loader_ready" in events
    assert "flow_completed" in events
    # The payload step ran
    assert patched_io["payloads"], "payload should have been sent after loader"
    # History record
    runs = flow_history.get_runs()
    assert len(runs) == 1
    assert runs[0]["result"] == "completed"
    assert runs[0]["loader_port"] == 9021
    assert runs[0]["loader_waited_s"] is not None


def test_wait_for_loader_timeout_fails_flow(tmp_profile, patched_io, tmp_history, monkeypatch):
    name = tmp_profile(
        '# ~notify flow_failed=on\n'
        '??9021 2 1 1\n'              # max 2 s, poll 1 s
        'kpayload.elf\n'              # MUST NOT run
    )
    patched_io["port_plan"] = [False] * 50

    async def scenario():
        return await exec_engine.run_autoload(AutoloadRequest(
            host="10.0.0.5", profile=name, continue_on_error=False,
        ))

    result = asyncio.run(scenario())
    assert result["success"] is False
    # No payload sent
    assert patched_io["payloads"] == []
    # flow_failed notification fired
    events = [n["event"] for n in patched_io["notifications"]]
    assert "flow_failed" in events
    # History records failed_timeout
    runs = flow_history.get_runs()
    assert runs[0]["result"] == "failed_timeout"
    assert "not detected in time" in runs[0]["error"]


def test_wait_for_loader_requires_stability(tmp_profile, patched_io, tmp_history):
    """With stability=2 a single True must NOT advance the step."""
    name = tmp_profile(
        '# ~notify loader_ready=on\n'
        '??9021 60 1 2\n'             # need 2 consecutive
    )
    patched_io["port_plan"] = [True, False, True, True]

    async def scenario():
        return await exec_engine.run_autoload(AutoloadRequest(
            host="10.0.0.5", profile=name,
        ))

    asyncio.run(scenario())
    # 4 polls: T, F, T, T → reaches stability=2 on poll 4
    polls = [p["ok"] for p in patched_io["polls"]]
    assert polls == [True, False, True, True]
    runs = flow_history.get_runs()
    assert runs[0]["result"] == "completed"


def test_notify_directive_fires_message(tmp_profile, patched_io, tmp_history):
    name = tmp_profile(
        '# ~notify loader_ready=off\n'
        '@notify "Heads up" "Body text"\n'
    )

    async def scenario():
        return await exec_engine.run_autoload(AutoloadRequest(
            host="10.0.0.5", profile=name,
        ))

    asyncio.run(scenario())
    customs = [n for n in patched_io["notifications"] if n["event"] == "@notify"]
    assert customs and customs[0]["title"] == "Heads up"
    assert customs[0]["msg"] == "Body text"


def test_flow_lifecycle_notifications_respect_toggles(tmp_profile, patched_io, tmp_history):
    """flow_started=off, flow_completed=on → only completion fires."""
    name = tmp_profile(
        '# ~notify flow_started=off flow_completed=on\n'
        '!10\n'                       # 10 ms delay, single step
    )

    async def scenario():
        return await exec_engine.run_autoload(AutoloadRequest(
            host="10.0.0.5", profile=name,
        ))

    asyncio.run(scenario())
    events = [n["event"] for n in patched_io["notifications"]]
    assert "flow_started" not in events
    assert "flow_completed" in events
