"""
P2JB / Patience loader-ready monitor.

The user starts P2JB / Patience manually on the PS5 — this monitor does
not trigger any exploit. It only polls the ELF loader port (default 9021)
on the configured PS5 IP and reacts when the loader becomes reachable
(jailbreak success). Optionally it can then auto-run a saved flow and
fire Home Assistant notifications.

State machine:

    idle ──start──► waiting ──port reachable──► loader_ready
                       │                            │
                       │                            │ (if auto_run)
                       │                            ▼
                       │                       running_flow
                       │                       │         │
                       │                       ▼         ▼
                       │                   completed  failed
                       │
                       └── max_wait elapsed ──► timeout
                       └── user cancel ──────► stopped

Concurrency rule (user chose "Monitor blockiert"): start_monitor fails
if exec_engine is currently running/paused, and auto-run aborts if the
exec_engine becomes busy between loader-ready and run_autoload.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

from exec_engine import (
    ExecState,
    executor,
    get_exec_state,
    run_autoload,
)
from ha_client import send_monitor_notification
from models import AutoloadRequest, P2JBMonitorConfig
from port_checker import check_port
from websocket_manager import manager

_log = logging.getLogger("ps5_autopayload")


class MonitorState:
    IDLE          = "idle"
    WAITING       = "waiting"
    LOADER_READY  = "loader_ready"
    RUNNING_FLOW  = "running_flow"
    COMPLETED     = "completed"
    FAILED        = "failed"
    TIMEOUT       = "timeout"
    STOPPED       = "stopped"


# ── Module-level state ────────────────────────────────────────────

_state: str = MonitorState.IDLE
_task:  Optional[asyncio.Task] = None
_config: Optional[P2JBMonitorConfig] = None
_started_at: Optional[float] = None
_last_check_at: Optional[float] = None
_loader_ready_at: Optional[float] = None
_last_error: Optional[str] = None
_lock: asyncio.Lock = asyncio.Lock()


# ── Public API ────────────────────────────────────────────────────

def get_status() -> Dict[str, Any]:
    """Snapshot for the UI. Always safe to call (no async needed)."""
    now = time.monotonic()
    elapsed = (now - _started_at) if _started_at else 0.0
    return {
        "state":           _state,
        "config":          _config.model_dump() if _config else None,
        "started_at":      _started_at,
        "elapsed_s":       round(elapsed, 1),
        "last_check_at":   _last_check_at,
        "loader_ready_at": _loader_ready_at,
        "last_error":      _last_error,
        "active":          _state in (
            MonitorState.WAITING,
            MonitorState.LOADER_READY,
            MonitorState.RUNNING_FLOW,
        ),
    }


async def start_monitor(config: P2JBMonitorConfig) -> Dict[str, Any]:
    """Validate, then kick off the background monitor task."""
    global _task, _config, _started_at, _last_check_at, _loader_ready_at, _last_error

    if _lock.locked() or _state in (
        MonitorState.WAITING, MonitorState.LOADER_READY, MonitorState.RUNNING_FLOW,
    ):
        raise RuntimeError("Monitor is already running")

    if get_exec_state() in (ExecState.RUNNING, ExecState.PAUSED):
        raise RuntimeError(
            "A builder flow is currently running. Stop it before starting the monitor."
        )

    if config.check_interval < 1.0:
        raise ValueError("check_interval must be ≥ 1 second")
    if config.max_wait < config.check_interval:
        raise ValueError("max_wait must be ≥ check_interval")
    if config.auto_run and not config.flow_name:
        raise ValueError("auto_run is enabled but flow_name is empty")

    _config          = config
    _started_at      = time.monotonic()
    _last_check_at   = None
    _loader_ready_at = None
    _last_error      = None

    _task = asyncio.create_task(_runner(), name="p2jb-monitor")
    await _set_state(MonitorState.WAITING)
    _log.info(
        "P2JB monitor started: host=%s elf_port=%s interval=%ss max_wait=%ss auto_run=%s flow=%s",
        config.host, config.elf_port, config.check_interval, config.max_wait,
        config.auto_run, config.flow_name,
    )
    return get_status()


async def stop_monitor() -> Dict[str, Any]:
    """User cancellation. Idempotent."""
    global _task
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            _log.warning("stop_monitor: task ended with %s", exc)
    _task = None
    if _state in (MonitorState.WAITING, MonitorState.LOADER_READY, MonitorState.RUNNING_FLOW):
        await _set_state(MonitorState.STOPPED)
        _log.info("P2JB monitor stopped by user")
    return get_status()


# ── Internal state-transition helper ──────────────────────────────

async def _set_state(new_state: str, **extra: Any) -> None:
    """Set state and broadcast over WebSocket."""
    global _state
    _state = new_state
    payload = {"type": "p2jb_state", "state": new_state, **get_status(), **extra}
    await manager.broadcast(payload)


# ── Background runner ─────────────────────────────────────────────

async def _runner() -> None:
    """The monitor loop. Polls the ELF port until reachable / timeout / cancelled."""
    global _last_check_at, _loader_ready_at, _last_error

    assert _config is not None
    cfg = _config

    try:
        async with _lock:
            poll_count = 0
            loop_start = time.monotonic()
            connect_timeout = max(1.0, min(5.0, cfg.check_interval / 2))

            while True:
                # Cancellation / timeout checks first so we never do another
                # connect attempt after the user hits Stop.
                if (time.monotonic() - loop_start) >= cfg.max_wait:
                    await _on_timeout()
                    return

                poll_count += 1
                _last_check_at = time.monotonic()
                _log.debug(
                    "P2JB poll #%d → %s:%s (connect_timeout=%.1fs)",
                    poll_count, cfg.host, cfg.elf_port, connect_timeout,
                )

                elf_ok = await check_port(cfg.host, cfg.elf_port, timeout=connect_timeout)
                lua_ok: Optional[bool] = None
                if cfg.lua_port:
                    lua_ok = await check_port(cfg.host, cfg.lua_port, timeout=connect_timeout)

                # Broadcast each check so the UI can show "Checking port 9021…"
                await manager.broadcast({
                    "type": "p2jb_check",
                    "poll": poll_count,
                    "elf_ok": elf_ok,
                    "lua_ok": lua_ok,
                    "elapsed_s": round(time.monotonic() - loop_start, 1),
                })

                if elf_ok:
                    await _on_loader_ready()
                    return

                # Not yet — sleep until next poll (cancellation aware).
                await asyncio.sleep(cfg.check_interval)

    except asyncio.CancelledError:
        # stop_monitor() drives the state transition; just exit quietly.
        _log.info("P2JB monitor cancelled")
        raise
    except Exception as exc:
        _last_error = str(exc)
        _log.exception("P2JB monitor crashed: %s", exc)
        await _set_state(MonitorState.FAILED, error=str(exc))


async def _on_loader_ready() -> None:
    """ELF port came up. Notify, maybe auto-run."""
    global _loader_ready_at
    assert _config is not None
    cfg = _config

    _loader_ready_at = time.monotonic()
    waited_s = round(_loader_ready_at - (_started_at or _loader_ready_at), 1)
    _log.info("P2JB loader ready on %s:%s after %.1fs", cfg.host, cfg.elf_port, waited_s)
    await _set_state(MonitorState.LOADER_READY)

    if cfg.notify_loader_ready:
        title = "PS5 ELF Loader is ready"
        msg = (
            f"Host: {cfg.host}\n"
            f"Port: {cfg.elf_port}\n"
            f"Waited: {_fmt_duration(waited_s)}"
        )
        await _notify(title, msg)

    if not cfg.auto_run:
        return  # terminal — user wanted notify-only

    if not cfg.flow_name:
        _log.warning("auto_run enabled but flow_name is empty — skipping")
        return

    # Re-check exec_engine — it may have started running between
    # monitor start and loader ready.
    if get_exec_state() in (ExecState.RUNNING, ExecState.PAUSED):
        msg = "A builder flow started while waiting — auto-run aborted"
        _log.warning(msg)
        await _on_failed(cfg.flow_name, msg)
        return

    await _run_flow(cfg)


async def _run_flow(cfg: P2JBMonitorConfig) -> None:
    """Invoke run_autoload and transition COMPLETED / FAILED accordingly."""
    flow = cfg.flow_name or ""
    safe = flow if flow.endswith(".txt") else f"{flow}.txt"
    await _set_state(MonitorState.RUNNING_FLOW, flow=safe)
    _log.info("P2JB monitor auto-run: flow=%s host=%s", safe, cfg.host)

    if cfg.notify_flow_started:
        await _notify("PS5 flow started", f"Flow: {flow}")

    try:
        result = await run_autoload(AutoloadRequest(
            host=cfg.host,
            profile=safe,
            continue_on_error=False,
        ))
    except Exception as exc:
        await _on_failed(flow, str(exc))
        return

    success = bool(result.get("success", False))
    if success:
        await _on_completed(flow, int(result.get("steps", 0)))
    else:
        await _on_failed(flow, result.get("message") or "flow did not complete")


async def _on_completed(flow: str, steps: int) -> None:
    await _set_state(MonitorState.COMPLETED, flow=flow, steps=steps)
    _log.info("P2JB monitor completed: flow=%s steps=%d", flow, steps)
    assert _config is not None
    if _config.notify_flow_completed:
        await _notify("PS5 flow completed successfully",
                      f"Flow: {flow}\nPayloads sent: {steps}")


async def _on_failed(flow: str, reason: str) -> None:
    global _last_error
    _last_error = reason
    await _set_state(MonitorState.FAILED, flow=flow, error=reason)
    _log.error("P2JB monitor failed: flow=%s reason=%s", flow, reason)
    assert _config is not None
    if _config.notify_flow_failed:
        await _notify("PS5 flow failed or timed out",
                      f"Flow: {flow}\nReason: {reason}")


async def _on_timeout() -> None:
    global _last_error
    assert _config is not None
    cfg = _config
    waited = round(time.monotonic() - (_started_at or 0.0), 1)
    _last_error = f"loader did not become reachable within {_fmt_duration(waited)}"
    await _set_state(MonitorState.TIMEOUT, waited_s=waited)
    _log.warning("P2JB monitor timeout: %s after %.1fs", cfg.host, waited)
    if cfg.notify_flow_failed:
        await _notify(
            "PS5 ELF Loader timeout",
            f"Host: {cfg.host}\nPort: {cfg.elf_port}\nWaited: {_fmt_duration(waited)}",
        )


# ── Helpers ───────────────────────────────────────────────────────

async def _notify(title: str, message: str) -> None:
    """Offload the blocking urllib call to the shared executor."""
    if not _config:
        return
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(
            executor, send_monitor_notification, title, message, _config.notify_service,
        )
    except Exception as exc:
        _log.warning("Notification dispatch failed: %s", exc)


def _fmt_duration(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"
