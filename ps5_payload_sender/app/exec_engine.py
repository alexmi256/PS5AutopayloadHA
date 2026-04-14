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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from autoload_parser import (
    DelayDirective,
    SendDirective,
    WaitPortDirective,
    parse_autoload_path,
)
from config import PROFILES_DIR
from ha_client import push_ha_state
from models import AutoloadRequest
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


# ── Runner ────────────────────────────────────────────────────────

async def run_autoload(req: AutoloadRequest) -> dict:
    """Execute *req.profile* step by step. Raises RuntimeError if already running."""
    if _run_lock.locked() or _exec_state in (ExecState.RUNNING, ExecState.PAUSED):
        raise RuntimeError("An execution is already in progress")

    safe = Path(req.profile).name
    path = PROFILES_DIR / safe
    if not path.exists():
        raise FileNotFoundError(f"Profile not found: {safe}")

    directives = parse_autoload_path(path)
    if not directives:
        return {"success": True, "message": "No directives", "steps": 0}

    async with _run_lock:
        _stop_event.clear()
        _pause_event.set()    # ensure unpaused at start
        await set_exec_state(ExecState.RUNNING, profile=safe)
        await manager.status(f"▶ Autoload '{safe}' – {len(directives)} steps …")

        results, aborted, stopped = [], False, False

        async def _check_stop_pause() -> bool:
            """Wait while paused; return True if stop was requested."""
            await _pause_event.wait()
            return _stop_event.is_set()

        for i, d in enumerate(directives, 1):
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

        # ── Final state ───────────────────────────────────────────
        if stopped:
            summary, level, final_state = "■ Stopped", "warn", ExecState.STOPPED
        elif aborted:
            all_ok = all(r.get("success", True) for r in results)
            if all_ok:
                summary, level, final_state = "Completed ✓", "success", ExecState.COMPLETED
            else:
                summary, level, final_state = "Aborted ✗", "error", ExecState.FAILED
        else:
            all_ok = all(r.get("success", True) for r in results)
            summary     = "Completed ✓" if all_ok else "Completed with errors"
            level       = "success" if all_ok else "error"
            final_state = ExecState.COMPLETED if all_ok else ExecState.FAILED

        await manager.status(summary, level=level)
        await set_exec_state(final_state, profile=safe)
        await asyncio.sleep(2)   # let UI show final state before resetting
        await set_exec_state(ExecState.IDLE)

        return {
            "success": not aborted and not stopped,
            "aborted": aborted,
            "stopped": stopped,
            "steps": len(directives),
        }
