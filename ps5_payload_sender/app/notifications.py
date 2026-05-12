"""
Flow notification dispatcher.

A flow profile carries a ``# ~notify …`` header with four event toggles
(loader_ready, flow_started, flow_completed, flow_failed) and an
optional ``notify.<service>`` target. This module consolidates the
logic for firing those notifications during real flow execution AND
for the Advanced-mode test buttons.

The actual HTTP call lives in :mod:`ha_client` — this module only
decides whether to call it, with which title/message, and (for the
async paths) offloads the blocking urllib call onto the shared
executor.

Notification reach (per the user spec):
  * persistent_notification is *always* used as the baseline.
  * If ``service`` is set, notify.<service> fires on top.
  * Validation: ``service`` must start with ``notify.`` — enforced at
    the request boundary (router) so this module trusts its input.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from functools import partial

from ha_client import send_monitor_notification
from websocket_manager import manager

_log = logging.getLogger("ps5_autopayload")


# ── Event titles ──────────────────────────────────────────────────

EVENT_TITLES: Dict[str, str] = {
    "loader_ready":   "PS5 ELF Loader is ready",
    "flow_started":   "PS5 flow started",
    "flow_completed": "PS5 flow completed successfully",
    "flow_failed":    "PS5 flow failed or timed out",
}


def event_enabled(notify_cfg: Dict[str, Any], event: str) -> bool:
    """Return True if the user has enabled notifications for *event*."""
    return bool(notify_cfg.get(event, False))


# ── Core dispatcher ───────────────────────────────────────────────

async def fire(
    event: str,
    notify_cfg: Dict[str, Any],
    *,
    title_suffix: str = "",
    message: str = "",
    service_override: Optional[str] = None,
) -> Dict[str, Any]:
    """Send a notification for *event* using *notify_cfg* preferences.

    Returns ``{persistent, service}`` so callers can log dispatch
    results. Does *not* respect ``event_enabled`` — callers gate the
    call themselves so they can also log the skip if useful.
    """
    title = EVENT_TITLES.get(event, event.replace("_", " ").title()) + title_suffix
    service = service_override or (notify_cfg.get("service") or None)
    # Persistent default = True so callers that pass an old-style cfg
    # (no key) keep getting persistent_notification.create. Set to False
    # only when the user explicitly toggled it off in the flow header.
    persistent = bool(notify_cfg.get("persistent", True))
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            partial(send_monitor_notification, title, message, service,
                    persistent=persistent),
        )
        _log.info(
            "Flow notification dispatched: event=%s service=%s persistent=%s service_ok=%s",
            event, service or "<persistent only>",
            result.get("persistent"), result.get("service"),
        )
        return {"event": event, "title": title, "service": service, **result}
    except Exception as exc:
        _log.exception("Flow notification failed: %s", exc)
        return {
            "event": event, "title": title, "service": service,
            "persistent": False, "error": str(exc),
        }


async def fire_if_enabled(
    event: str,
    notify_cfg: Dict[str, Any],
    *,
    message: str = "",
    service_override: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Convenience wrapper for the in-flow lifecycle hooks."""
    if not event_enabled(notify_cfg, event):
        _log.debug("Skipping %s notification (disabled by flow config)", event)
        return None
    return await fire(event, notify_cfg, message=message,
                      service_override=service_override)


# ── Free-form notify step ─────────────────────────────────────────

async def fire_custom(
    title: str,
    message: str,
    notify_cfg: Dict[str, Any],
    *,
    service_override: Optional[str] = None,
) -> Dict[str, Any]:
    """Send a notification with an arbitrary title/message (the
    `@notify` step). Always sends — there's no event gate."""
    service = service_override or (notify_cfg.get("service") or None)
    persistent = bool(notify_cfg.get("persistent", True))
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            partial(send_monitor_notification, title, message, service,
                    persistent=persistent),
        )
        _log.info("@notify step dispatched: service=%s persistent=%s service_ok=%s",
                  service or "<persistent only>",
                  result.get("persistent"), result.get("service"))
        return {"title": title, "service": service, **result}
    except Exception as exc:
        _log.exception("@notify step failed: %s", exc)
        return {"title": title, "service": service, "persistent": False, "error": str(exc)}


# ── Test + simulation (Advanced Mode) ─────────────────────────────

def _build_test_message(event: str, *, host: str, port: int, flow: str) -> str:
    """Sample body for the four test events."""
    host = host or "(no host)"
    flow = flow or "(no flow)"
    if event == "loader_ready":
        body = f"Host: {host}\nPort: {port}\nWaited: 1h 23m (sample)"
    elif event == "flow_started":
        body = f"Flow: {flow}"
    elif event == "flow_completed":
        body = f"Flow: {flow}\nPayloads sent: 4 (sample)"
    elif event == "flow_failed":
        body = f"Flow: {flow}\nReason: sample failure reason"
    elif event == "persistent":
        body = "This is a test of the Home Assistant persistent notification path."
    elif event == "service":
        body = "This is a test of the notify.<service> path configured for this flow."
    else:
        body = ""
    return body + "\n\n[TEST] No real loader was detected."


async def test_notification(
    event: str,
    notify_cfg: Dict[str, Any],
    *,
    host: str = "",
    port: int = 9021,
    flow_name: str = "",
) -> Dict[str, Any]:
    """Fire a single representative notification for *event* without
    touching any real flow state. Returns a result dict suitable for
    the UI's success/failure toast."""
    allowed = {"persistent", "service",
               "loader_ready", "flow_started", "flow_completed", "flow_failed"}
    if event not in allowed:
        raise ValueError(f"Unknown test event: {event!r}")

    if event == "persistent":
        title = "PS5 Autopayload — persistent notification test"
        # "Test persistent" specifically exercises the HA notification
        # center path, regardless of how the flow has it configured.
        message = _build_test_message(event, host=host, port=port, flow=flow_name)
        return await _dispatch_test(title, message, service=None, persistent=True, event=event)

    if event == "service":
        svc = (notify_cfg.get("service") or "").strip()
        if not svc:
            return {
                "success": False, "event": event,
                "error": "no notify.<service> configured for this flow",
            }
        title = f"PS5 Autopayload — {svc} test"
        message = _build_test_message(event, host=host, port=port, flow=flow_name)
        # "Test custom notify service" specifically validates the
        # notify.<service> hop — persistent is intentionally off so the
        # user can isolate the failure.
        return await _dispatch_test(title, message, service=svc, persistent=False, event=event)

    # Real-event simulations honour the flow's persistent toggle.
    title = EVENT_TITLES[event] + " (test)"
    service = (notify_cfg.get("service") or None)
    persistent = bool(notify_cfg.get("persistent", True))
    message = _build_test_message(event, host=host, port=port, flow=flow_name)
    return await _dispatch_test(title, message, service=service,
                                persistent=persistent, event=event)


async def _dispatch_test(
    title: str, message: str, service: Optional[str], event: str,
    *, persistent: bool = True,
) -> Dict[str, Any]:
    loop = asyncio.get_running_loop()
    _log.info("Flow Notification: Test started — event=%s service=%s persistent=%s",
              event, service or "<none>", persistent)
    try:
        result = await loop.run_in_executor(
            None,
            partial(send_monitor_notification, title, message, service,
                    persistent=persistent),
        )
        # success := every channel the caller asked for came back True.
        pn_ok  = result.get("persistent")
        svc_ok = result.get("service")
        success = ((not persistent) or pn_ok is True) and \
                  ((service is None) or svc_ok is True)
        if success:
            _log.info("Flow Notification: Test sent successfully (%s)", event)
        else:
            _log.error(
                "Flow Notification: %s test failed (persistent=%s service=%s)",
                event, result.get("persistent"), result.get("service"),
            )
        if success:
            err = None
        elif service and svc_ok is False:
            err = f"notify.{service} unreachable"
        elif persistent and pn_ok is False:
            err = "persistent notification failed"
        else:
            err = "no delivery channel succeeded"
        return {
            "success":    success,
            "event":      event,
            "title":      title,
            "persistent": pn_ok,
            "service":    svc_ok,
            "error":      err,
        }
    except Exception as exc:
        _log.exception("Flow Notification: Test exception: %s", exc)
        return {"success": False, "event": event, "title": title, "error": str(exc)}


async def simulate_loader_ready(
    notify_cfg: Dict[str, Any],
    *,
    host: str = "",
    port: int = 9021,
) -> Dict[str, Any]:
    """Broadcast a UI-only ``flow_simulation`` WebSocket event and fire
    the loader-ready notification using *notify_cfg*. Never runs a flow.

    The optional "Run selected flow after simulated loader ready"
    behaviour lives in the router (it has to call into exec_engine).
    """
    _log.info("Flow Notification: simulated loader ready (host=%s port=%s)", host, port)
    await manager.broadcast({
        "type":  "flow_simulation",
        "event": "loader_ready",
        "host":  host,
        "port":  port,
    })
    if not event_enabled(notify_cfg, "loader_ready"):
        return {"success": True, "event": "loader_ready",
                "simulated": True, "notified": False}
    message = (
        f"Host: {host or 'n/a'}\nPort: {port}\n\n"
        "[TEST] No real loader was detected."
    )
    result = await fire(
        "loader_ready", notify_cfg,
        title_suffix=" (simulated)", message=message,
    )
    persistent_enabled = bool(notify_cfg.get("persistent", True))
    service_set        = bool(result.get("service") is not None)
    pn_ok              = result.get("persistent")
    svc_ok             = result.get("service")
    success = ((not persistent_enabled) or pn_ok is True) and \
              ((not service_set) or svc_ok is True)
    return {
        "success":   success,
        "event":     "loader_ready",
        "simulated": True,
        "notified":  True,
        **result,
    }
