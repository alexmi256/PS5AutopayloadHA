from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException

import flow_analysis
import port_timing
from exec_engine import executor
from models import FlowAnalyzeRequest
from payload_sender import resolve_port, send_payload
from port_checker import check_port

router = APIRouter()


@router.post("/api/flow/analyze")
async def api_flow_analyze(req: FlowAnalyzeRequest):
    """
    Execute builder steps with per-step timing.
    In safe_mode=True payloads are tracked but not actually sent.
    Returns a full run record with timeline steps.
    """
    if not req.steps:
        raise HTTPException(400, "No steps to analyze")

    loop = asyncio.get_running_loop()
    run_start   = loop.time()
    wall_start  = time.time()
    steps_out: list = []

    for step in req.steps:
        step_t0  = loop.time()
        offset_s = round(step_t0 - run_start, 2)

        if step.type == "wait_port":
            interval_s = max(0.1, step.interval_ms / 1000)
            t0 = loop.time()
            reached = False
            while loop.time() - t0 < step.timeout:
                if await check_port(req.host, step.port, timeout=2.0):
                    reached = True
                    break
                await asyncio.sleep(interval_s)
            dur_ms = int((loop.time() - step_t0) * 1000)
            steps_out.append({
                "type": "wait_port", "port": step.port,
                "reached": reached, "duration_ms": dur_ms, "offset_s": offset_s,
            })
            if reached:
                await loop.run_in_executor(executor, port_timing.record, step.port, dur_ms, "", "")

        elif step.type == "delay":
            await asyncio.sleep(step.ms / 1000)
            dur_ms = step.ms
            steps_out.append({
                "type": "delay", "ms": step.ms,
                "duration_ms": dur_ms, "offset_s": offset_s,
            })

        elif step.type == "payload":
            eff_port = step.portOverride or step.autoPort or resolve_port(step.filename, None)
            if req.safe_mode:
                steps_out.append({
                    "type": "payload", "filename": step.filename, "port": eff_port,
                    "safe_mode": True, "success": None, "duration_ms": 0,
                    "offset_s": offset_s,
                })
            else:
                result  = await send_payload(req.host, eff_port, step.filename)
                dur_ms  = int((loop.time() - step_t0) * 1000)
                steps_out.append({
                    "type": "payload", "filename": step.filename, "port": eff_port,
                    "safe_mode": False, "success": result.get("success"),
                    "duration_ms": dur_ms, "offset_s": offset_s,
                })

    total_ms = int((loop.time() - run_start) * 1000)
    run = {
        "id":         int(wall_start * 1000),
        "started_at": wall_start,
        "total_ms":   total_ms,
        "safe_mode":  req.safe_mode,
        "steps":      steps_out,
    }
    await loop.run_in_executor(executor, flow_analysis.record_run, run)
    return {"run": run}


@router.get("/api/flow/runs")
async def api_flow_runs():
    loop = asyncio.get_running_loop()
    runs = await loop.run_in_executor(executor, flow_analysis.get_runs)
    return {"runs": runs}


@router.delete("/api/flow/runs")
async def api_flow_clear():
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, flow_analysis.clear_runs)
    return {"success": True}


@router.get("/api/flow/stats")
async def api_flow_stats():
    loop = asyncio.get_running_loop()
    stats = await loop.run_in_executor(executor, flow_analysis.get_stats)
    return stats
