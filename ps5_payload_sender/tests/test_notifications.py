"""Tests for the flow notification dispatcher.

These tests stub out ``ha_client.send_monitor_notification`` so they
never touch the Supervisor API. They verify gating (event toggles),
service-override behaviour, validation of the test endpoint events,
and the simulation broadcast.
"""
from __future__ import annotations

import asyncio

import pytest

import notifications


# ── Stubs ────────────────────────────────────────────────────────


@pytest.fixture
def fake_notifier(monkeypatch):
    """Capture every notification call. The returned ``calls`` list
    grows as tests trigger notifications; ``set_result()`` lets a test
    control the dispatch outcome."""
    state = {"result": {"persistent": True, "service": True}}
    calls = []

    def _send(title, message, service):
        calls.append({"title": title, "message": message, "service": service})
        r = dict(state["result"])
        if service is None:
            r.pop("service", None)
            r["service"] = None
        elif r.get("service") is True:
            r["service"] = True
        return r

    monkeypatch.setattr(notifications, "send_monitor_notification", _send)

    class _Setter:
        def __init__(self):
            self.calls = calls
        def set_result(self, **kw):
            state["result"].update(kw)
    return _Setter()


# ── Gating: fire_if_enabled honours flag ─────────────────────────


def test_fire_if_enabled_skips_when_disabled(fake_notifier):
    cfg = {"loader_ready": False, "service": ""}

    async def scenario():
        r = await notifications.fire_if_enabled("loader_ready", cfg, message="x")
        assert r is None

    asyncio.run(scenario())
    assert fake_notifier.calls == []


def test_fire_if_enabled_dispatches_when_enabled(fake_notifier):
    cfg = {"loader_ready": True, "service": "notify.foo"}

    async def scenario():
        return await notifications.fire_if_enabled(
            "loader_ready", cfg, message="Body",
        )

    r = asyncio.run(scenario())
    assert r is not None
    assert r["event"] == "loader_ready"
    assert fake_notifier.calls
    assert fake_notifier.calls[0]["service"] == "notify.foo"


# ── Service override at call site ────────────────────────────────


def test_service_override_takes_precedence(fake_notifier):
    cfg = {"loader_ready": True, "service": "notify.default"}

    async def scenario():
        await notifications.fire_if_enabled(
            "loader_ready", cfg, message="x", service_override="notify.over",
        )

    asyncio.run(scenario())
    assert fake_notifier.calls[0]["service"] == "notify.over"


# ── Custom @notify step ──────────────────────────────────────────


def test_fire_custom_always_sends_regardless_of_toggles(fake_notifier):
    cfg = {"loader_ready": False, "flow_completed": False, "service": ""}

    async def scenario():
        return await notifications.fire_custom("Title", "Body", cfg)

    r = asyncio.run(scenario())
    assert r["title"] == "Title"
    assert fake_notifier.calls[0]["title"] == "Title"


# ── Test endpoint events ─────────────────────────────────────────


def test_test_notification_rejects_unknown_event(fake_notifier):
    async def scenario():
        with pytest.raises(ValueError):
            await notifications.test_notification("bogus", {})
    asyncio.run(scenario())


def test_test_notification_persistent_forces_no_service(fake_notifier):
    """The 'persistent' test must skip the notify.<service> hop even if
    one is configured, since it specifically tests the persistent path."""
    cfg = {"service": "notify.foo"}

    async def scenario():
        return await notifications.test_notification("persistent", cfg)

    r = asyncio.run(scenario())
    # _dispatch_test was called with service=None for the persistent test
    assert r["success"] is True
    assert fake_notifier.calls[0]["service"] is None


def test_test_notification_service_requires_configured_service(fake_notifier):
    async def scenario():
        return await notifications.test_notification("service", {"service": ""})

    r = asyncio.run(scenario())
    assert r["success"] is False
    assert "no notify" in r["error"].lower()


def test_test_notification_event_uses_flow_service(fake_notifier):
    cfg = {"service": "notify.mob"}

    async def scenario():
        return await notifications.test_notification(
            "flow_completed", cfg, flow_name="Foo", host="1.2.3.4",
        )

    r = asyncio.run(scenario())
    assert r["success"] is True
    assert fake_notifier.calls[0]["service"] == "notify.mob"
    assert r["title"].endswith("(test)")


def test_test_notification_reports_failure_when_service_unreachable(fake_notifier):
    fake_notifier.set_result(persistent=True, service=False)
    cfg = {"service": "notify.mob"}

    async def scenario():
        return await notifications.test_notification("loader_ready", cfg)

    r = asyncio.run(scenario())
    assert r["success"] is False
    assert "unreachable" in r["error"]


# ── Simulation ───────────────────────────────────────────────────


def test_simulate_loader_ready_skips_notification_when_disabled(fake_notifier):
    cfg = {"loader_ready": False, "service": ""}

    async def scenario():
        return await notifications.simulate_loader_ready(cfg, host="x", port=9021)

    r = asyncio.run(scenario())
    assert r["simulated"] is True
    assert r["notified"] is False
    assert fake_notifier.calls == []


def test_simulate_loader_ready_fires_notification_when_enabled(fake_notifier):
    cfg = {"loader_ready": True, "service": "notify.foo"}

    async def scenario():
        return await notifications.simulate_loader_ready(cfg, host="1.2.3.4", port=9021)

    r = asyncio.run(scenario())
    assert r["notified"] is True
    assert fake_notifier.calls
    assert "(simulated)" in fake_notifier.calls[0]["title"]
