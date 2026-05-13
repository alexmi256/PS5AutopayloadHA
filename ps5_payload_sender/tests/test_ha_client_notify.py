"""Boundary test: ``send_notify_service`` must strip the ``notify.``
prefix before building the HA REST URL — otherwise the URL becomes
``/core/api/services/notify/notify.<service>``, which Home Assistant
rejects.

The Pydantic validator on ``FlowNotifyConfig.service`` *requires* the
prefix in user-facing config, so the prefix MUST be stripped at the
boundary, not earlier in the dispatcher.
"""
from __future__ import annotations

from unittest.mock import patch

import ha_client


def test_send_notify_service_strips_notify_prefix(monkeypatch):
    captured = {}

    def _fake_call(domain, service, data, timeout=5.0):
        captured["domain"]  = domain
        captured["service"] = service
        captured["data"]    = data
        return True

    monkeypatch.setattr(ha_client, "_call_ha_service", _fake_call)
    ok = ha_client.send_notify_service("notify.mobile_app_iphone", "T", "M")
    assert ok is True
    assert captured["domain"]  == "notify"
    assert captured["service"] == "mobile_app_iphone"   # stripped!


def test_send_notify_service_accepts_bare_service_name(monkeypatch):
    """Defensive: if a caller passes the bare name without prefix,
    it still works (idempotent stripping)."""
    captured = {}
    monkeypatch.setattr(ha_client, "_call_ha_service",
                        lambda d, s, dd, timeout=5.0: captured.setdefault("service", s) or True)
    ha_client.send_notify_service("mobile_app_iphone", "T", "M")
    assert captured["service"] == "mobile_app_iphone"


def test_send_notify_service_rejects_empty_after_strip(monkeypatch):
    """A naked 'notify.' must not produce an empty service name."""
    called = {"n": 0}
    def _fake_call(*a, **k):
        called["n"] += 1
        return True
    monkeypatch.setattr(ha_client, "_call_ha_service", _fake_call)
    assert ha_client.send_notify_service("notify.", "T", "M") is False
    assert called["n"] == 0       # no REST call made
