"""
Execution state machine and autoload runner.

Public API:
  get_exec_state()          – current state string
  set_exec_state(val, ...)  – update state, broadcast via WS, push to HA
  run_autoload(req)         – execute an AutoloadRequest profile
  request_stop()            – signal the runner to stop
  request_pause()           – pause the runner
  request_resume()          – resume the runner
"""
from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from autoload_parser import (
    DelayDirective,
    NotifyDirective,
    SendDirective,
    WaitForLoaderDirective,
    WaitPortDirective,
    parse_autoload_file,
    parse_notify_config,
)
from config import PROFILES_DIR
import flow_history
from ha_client import push_ha_state
from models import AutoloadRequest
import notifications
from payload_sender import resolve_port, send_payload
from port_checker import check_port
from websocket_manager import manager

_log = logging.getLogger("ps5_autopayload")

# Shared thread-pool (used here and in main.py startup)
executor = ThreadPoolExecutor(max_workers=2)

# ── State constants ───────────────────────────────────────────────

class ExecState:
    IDLE      = "idle"
    RUNNING   = "running"
    PAUSED    = "paused"
    STOPPED   = "stopped"
    COMPLETED = "completed"
    FAILED    = "failed"

# ── Module-level state ────────────────────────────────────────────

_exec_state: str           = ExecState.IDLE
_stop_event:  asyncio.Event = asyncio.Event()   # set → stop requested
_pause_event: asyncio.Event = asyncio.Event()   # set → NOT paused (running)
_run_lock:    asyncio.Lock  = asyncio.Lock()

_pause_event.set()   # start unpaused


# ── Public accessors ──────────────────────────────────────────────

def get_exec_state() -> str:
    return _exec_state


async def set_exec_state(state_val: str, profile: str = "") -> None:
    global _exec_state
    _exec_state = state_val
    await manager.broadcast({"type": "exec_state", "state": state_val, "profile": profile})
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, push_ha_state, state_val)


def request_stop() -> None:
    _stop_event.set()
    _pause_event.set()   # unblock pause so the loop can exit


def request_pause() -> bool:
    """Returns False if not currently running."""
    if _exec_state != ExecState.RUNNING:
        return False
    _pause_event.clear()
    return True


def request_resume() -> bool:
    """Returns False if not currently paused."""
    if _exec_state != ExecState.PAUSED:
        return False
    _pause_event.set()
    return True


# ── Loader-poll helper ────────────────────────────────────────────

async def _poll_until_loader(
    *,
    host: str,
    port: int,
    max_wait_seconds: float,
    interval_seconds: float,
    stability_count: int = 1,
) -> dict:
    """Poll *host:port* every *interval_seconds* up to *max_wait_seconds*.

    Honors the module-level stop/pause events. Broadcasts a
    ``flow_wait_check`` WS event every poll so the UI can show a live
    progress overlay. Returns a dict:

      {"reached": bool, "stopped": bool, "elapsed": float, "polls": int}
    """
    connect_timeout = max(1.0, min(5.0, interval_seconds / 2))
    loop_start = asyncio.get_running_loop().time()
    consecutive_ok = 0
    poll = 0
    reached = False
    stopped = False
    while True:
        if _stop_event.is_set():
            stopped = True
            break
        await _pause_event.wait()
        poll += 1
        ok = await check_port(host, port, timeout=connect_timeout)
        consecutive_ok = consecutive_ok + 1 if ok else 0
        elapsed = asyncio.get_running_loop().time() - loop_start
        _log.debug(
            "loader poll #%d port=%s ok=%s consecutive=%s elapsed=%.0fs",
            poll, port, ok, consecutive_ok, elapsed,
        )
        await manager.broadcast({
            "type": "flow_wait_check",
            "port": port, "poll": poll,
            "ok": ok, "consecutive": consecutive_ok,
            "elapsed_s": round(elapsed, 1),
            "max_wait_s": max_wait_seconds,
        })
        if consecutive_ok >= max(1, stability_count):
            reached = True
            break
        if elapsed >= max_wait_seconds:
            break
        sleep_end = asyncio.get_running_loop().time() + interval_seconds
        while asyncio.get_running_loop().time() < sleep_end:
            if _stop_event.is_set():
                stopped = True
                break
            await _pause_event.wait()
            await asyncio.sleep(0.2)
        if stopped:
            break
    final_elapsed = asyncio.get_running_loop().time() - loop_start
    return {"reached": reached, "stopped": stopped,
            "elapsed": final_elapsed, "polls": poll}


# ── Runner ────────────────────────────────────────────────────────

def _fmt_duration(seconds: float) -> str:
    s = int(max(0, seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


async def run_autoload(req: AutoloadRequest) -> dict:
    """Execute *req.profile* step by step. Raises RuntimeError if already running."""
    if _run_lock.locked() or _exec_state in (ExecState.RUNNING, ExecState.PAUSED):
        raise RuntimeError("An execution is already in progress")

    safe = Path(req.profile).name
    path = PROFILES_DIR / safe
    if not path.exists():
        raise FileNotFoundError(f"Profile not found: {safe}")

    # Single read so directives + notify config come from the same snapshot.
    content    = path.read_text(encoding="utf-8", errors="replace")
    directives = parse_autoload_file(content)
    notify_cfg = parse_notify_config(content)
    if not directives:
        return {"success": True, "message": "No directives", "steps": 0}

    async with _run_lock:
        _stop_event.clear()
        _pause_event.set()    # ensure unpaused at start
        await set_exec_state(ExecState.RUNNING, profile=safe)
        await manager.status(f"▶ Autoload '{safe}' – {len(directives)} steps …")

        flow_start_wall      = time.time()
        flow_start_mono      = asyncio.get_running_loop().time()
        loader_wait_seconds: float | None = None
        loader_port:         int   | None = None
        loader_timeout       = False
        loader_timeout_msg   = ""

        # Fire flow_started notification (best-effort, never blocks the run)
        try:
            await notifications.fire_if_enabled(
                "flow_started", notify_cfg,
                message=f"Flow: {safe}\nHost: {req.host}",
            )
        except Exception as exc:
            _log.warning("flow_started notification failed: %s", exc)

        results, aborted, stopped = [], False, False

        # ── Phase 1: flow-level loader wait (replaces the WAIT FOR LOADER
        # step). Only runs when the flow's ~notify header sets
        # `wait_for_loader_enabled=on`. Times out → flow fails immediately,
        # no payload step runs. Loader reachable → continue to the step
        # loop below.
        if notify_cfg.get("wait_for_loader_enabled"):
            eff_port     = int(notify_cfg.get("loader_port") or 9021)
            eff_max_wait = float(notify_cfg.get("loader_max_wait_s") or 10800)
            eff_interval = float(notify_cfg.get("loader_interval_s") or 30)
            loader_port  = eff_port
            await manager.status(
                f"Waiting for loader on port {eff_port} "
                f"(max {_fmt_duration(eff_max_wait)}, every {eff_interval:.0f}s) …",
                waiting_port=eff_port,
            )
            _log.info(
                "Flow-level loader wait started: port=%s max_wait=%ss interval=%ss host=%s",
                eff_port, eff_max_wait, eff_interval, req.host,
            )
            poll_result = await _poll_until_loader(
                host=req.host, port=eff_port,
                max_wait_seconds=eff_max_wait, interval_seconds=eff_interval,
            )
            if poll_result["stopped"]:
                stopped = True
                await manager.status("■ Stopped", level="warn")
            elif poll_result["reached"]:
                loader_wait_seconds = poll_result["elapsed"]
                _log.info("Loader reachable on port %s after %.1fs",
                          eff_port, poll_result["elapsed"])
                await manager.status(
                    f"Loader on port {eff_port} reachable after "
                    f"{_fmt_duration(poll_result['elapsed'])} ✓",
                    level="success",
                )
                try:
                    await notifications.fire_if_enabled(
                        "loader_ready", notify_cfg,
                        message=(
                            f"Host: {req.host}\nPort: {eff_port}\n"
                            f"Waited: {_fmt_duration(poll_result['elapsed'])}"
                        ),
                    )
                except Exception as exc:
                    _log.warning("loader_ready notification failed: %s", exc)
            else:
                # Timeout — flow fails before any payload step runs.
                loader_timeout = True
                loader_wait_seconds = poll_result["elapsed"]
                waited_min = round(eff_max_wait / 60)
                loader_timeout_msg = (
                    f"PS5 loader was not detected within {waited_min} minutes "
                    f"on port {eff_port}"
                )
                _log.error("Flow-level loader wait timeout: %s", loader_timeout_msg)
                await manager.status(loader_timeout_msg, level="error")
                results.append({
                    "success": False, "message": loader_timeout_msg, "bytes_sent": 0,
                })
                aborted = True

        async def _check_stop_pause() -> bool:
            """Wait while paused; return True if stop was requested."""
            await _pause_event.wait()
            return _stop_event.is_set()

        # Skip the step loop entirely if the flow-level loader wait
        # already stopped or timed out — there's no point sending payloads.
        steps_iter = [] if (stopped or loader_timeout) else list(enumerate(directives, 1))
        for i, d in steps_iter:
            if await _check_stop_pause():
                stopped = True
                await manager.status("■ Stopped", level="warn")
                break

            if isinstance(d, SendDirective):
                port = resolve_port(d.filename, d.port)
                await manager.status(
                    f"[{i}/{len(directives)}] Sending '{d.filename}' → {req.host}:{port}"
                )
                r = await send_payload(req.host, port, d.filename)
                results.append(r)
                await manager.status(r["message"], level="success" if r["success"] else "error")
                if not r["success"] and not req.continue_on_error:
                    aborted = True
                    break

            elif isinstance(d, DelayDirective):
                await manager.status(f"[{i}/{len(directives)}] Delay {d.milliseconds} ms …")
                elapsed_ms = 0
                while elapsed_ms < d.milliseconds:
                    if _stop_event.is_set():
                        break
                    await _pause_event.wait()
                    await asyncio.sleep(0.1)
                    elapsed_ms += 100
                if _stop_event.is_set():
                    stopped = True
                    break

            elif isinstance(d, WaitPortDirective):
                interval_s = max(0.1, d.interval_ms / 1000)
                await manager.status(
                    f"[{i}/{len(directives)}] Waiting for port {d.port} "
                    f"(max {d.timeout_seconds}s, every {d.interval_ms}ms) …",
                    waiting_port=d.port,
                )
                loop_start = asyncio.get_running_loop().time()
                reached = False
                while True:
                    if _stop_event.is_set():
                        stopped = True
                        break
                    await _pause_event.wait()
                    if await check_port(req.host, d.port, timeout=2.0):
                        await manager.status(f"Port {d.port} reachable!", level="success")
                        reached = True
                        break
                    elapsed = asyncio.get_running_loop().time() - loop_start
                    if elapsed >= d.timeout_seconds:
                        break
                    await manager.status(
                        f"Waiting for port {d.port} … ({elapsed:.0f}/{d.timeout_seconds:.0f}s)",
                        waiting_port=d.port,
                    )
                    sleep_end = asyncio.get_running_loop().time() + interval_s
                    while asyncio.get_running_loop().time() < sleep_end:
                        if _stop_event.is_set():
                            break
                        await _pause_event.wait()
                        await asyncio.sleep(0.1)

                if stopped:
                    break
                if not reached:
                    msg = f"Timeout: port {d.port} not reachable"
                    await manager.status(msg, level="error")
                    results.append({"success": False, "message": msg, "bytes_sent": 0})
                    if not req.continue_on_error:
                        aborted = True
                        break

            elif isinstance(d, WaitForLoaderDirective):
                # Legacy directive — kept so old saved flows that still
                # carry `??` lines keep working. New flows use the
                # flow-level wait_for_loader_enabled toggle (Phase 1 above)
                # and emit no `??` directive at all.
                #
                # Guard: if the header already triggered the Phase 1 wait,
                # skip this directive — otherwise we'd block again on the
                # same port (a flow that hand-edited to have both would
                # wait twice). Status hint helps the user notice the
                # redundancy.
                if notify_cfg.get("wait_for_loader_enabled"):
                    _log.info(
                        "Skipping legacy ?? directive at step %d — flow-level "
                        "wait_for_loader_enabled already handled the wait", i,
                    )
                    await manager.status(
                        f"[{i}/{len(directives)}] WAIT FOR LOADER skipped "
                        f"(already handled by flow setting)",
                        level="info",
                    )
                    continue

                eff_port      = d.port or int(notify_cfg.get("loader_port") or 9021)
                eff_max_wait  = d.max_wait_seconds or float(notify_cfg.get("loader_max_wait_s") or 10800)
                eff_interval  = d.interval_seconds or float(notify_cfg.get("loader_interval_s") or 30)
                eff_stability = max(1, int(d.stability_count or 1))
                loader_port   = eff_port

                await manager.status(
                    f"[{i}/{len(directives)}] WAIT FOR LOADER on port {eff_port} "
                    f"(max {_fmt_duration(eff_max_wait)}, every {eff_interval:.0f}s, "
                    f"stability {eff_stability}) …",
                    waiting_port=eff_port,
                )
                _log.info(
                    "WAIT FOR LOADER started: port=%s max_wait=%ss interval=%ss stability=%s host=%s",
                    eff_port, eff_max_wait, eff_interval, eff_stability, req.host,
                )
                poll_result = await _poll_until_loader(
                    host=req.host, port=eff_port,
                    max_wait_seconds=eff_max_wait, interval_seconds=eff_interval,
                    stability_count=eff_stability,
                )
                if poll_result["stopped"]:
                    stopped = True
                    break
                if poll_result["reached"]:
                    loader_wait_seconds = poll_result["elapsed"]
                    _log.info(
                        "WAIT FOR LOADER detected: port=%s after %.1fs",
                        eff_port, poll_result["elapsed"],
                    )
                    await manager.status(
                        f"Loader on port {eff_port} reachable after "
                        f"{_fmt_duration(poll_result['elapsed'])} ✓",
                        level="success",
                    )
                    try:
                        await notifications.fire_if_enabled(
                            "loader_ready", notify_cfg,
                            message=(
                                f"Host: {req.host}\nPort: {eff_port}\n"
                                f"Waited: {_fmt_duration(poll_result['elapsed'])}"
                            ),
                        )
                    except Exception as exc:
                        _log.warning("loader_ready notification failed: %s", exc)
                else:
                    loader_timeout = True
                    loader_wait_seconds = poll_result["elapsed"]
                    waited_min = round(eff_max_wait / 60)
                    loader_timeout_msg = (
                        f"PS5 loader was not detected within {waited_min} minutes "
                        f"on port {eff_port}"
                    )
                    _log.error("WAIT FOR LOADER timeout: %s", loader_timeout_msg)
                    await manager.status(loader_timeout_msg, level="error")
                    results.append({
                        "success": False, "message": loader_timeout_msg, "bytes_sent": 0,
                    })
                    aborted = True
                    break

            elif isinstance(d, NotifyDirective):
                await manager.status(
                    f"[{i}/{len(directives)}] @notify '{d.title}' …", level="info",
                )
                try:
                    await notifications.fire_custom(
                        d.title, d.message, notify_cfg,
                        service_override=d.service_override,
                    )
                except Exception as exc:
                    _log.warning("@notify step failed: %s", exc)

        # ── Final state ───────────────────────────────────────────
        if stopped:
            summary, level, final_state = "■ Stopped", "warn", ExecState.STOPPED
            history_result = "stopped"
        elif loader_timeout:
            summary, level, final_state = "Loader timeout ✗", "error", ExecState.FAILED
            history_result = "failed_timeout"
        elif aborted:
            all_ok = all(r.get("success", True) for r in results)
            if all_ok:
                summary, level, final_state = "Completed ✓", "success", ExecState.COMPLETED
                history_result = "completed"
            else:
                summary, level, final_state = "Aborted ✗", "error", ExecState.FAILED
                history_result = "failed"
        else:
            all_ok = all(r.get("success", True) for r in results)
            summary     = "Completed ✓" if all_ok else "Completed with errors"
            level       = "success" if all_ok else "error"
            final_state = ExecState.COMPLETED if all_ok else ExecState.FAILED
            history_result = "completed" if all_ok else "failed"

        await manager.status(summary, level=level)
        await set_exec_state(final_state, profile=safe)

        # Lifecycle notifications + history record
        total_waited = asyncio.get_running_loop().time() - flow_start_mono
        try:
            if history_result == "completed":
                await notifications.fire_if_enabled(
                    "flow_completed", notify_cfg,
                    message=(
                        f"Flow: {safe}\nPayloads sent: "
                        f"{sum(1 for r in results if r.get('success'))}"
                    ),
                )
            elif history_result in ("failed", "failed_timeout"):
                reason = loader_timeout_msg or next(
                    (r.get("message", "") for r in results if not r.get("success", True)),
                    "flow failed",
                )
                await notifications.fire_if_enabled(
                    "flow_failed", notify_cfg,
                    message=f"Flow: {safe}\nReason: {reason}",
                )
        except Exception as exc:
            _log.warning("final-state notification failed: %s", exc)

        try:
            flow_history.record_run(
                started_at      = flow_start_wall,
                waited_s        = total_waited,
                loader_waited_s = loader_wait_seconds,
                host            = req.host,
                ps5_name        = flow_history.lookup_ps5_name(req.host),
                loader_port     = loader_port,
                flow_name       = safe,
                result          = history_result,
                error           = loader_timeout_msg or "",
                steps           = len(directives),
            )
        except Exception as exc:
            _log.warning("flow history record failed: %s", exc)

        await asyncio.sleep(2)   # let UI show final state before resetting
        await set_exec_state(ExecState.IDLE)

        return {
            "success": not aborted and not stopped,
            "aborted": aborted,
            "stopped": stopped,
            "steps": len(directives),
        }
