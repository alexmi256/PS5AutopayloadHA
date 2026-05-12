"""HTTP endpoints for flow notification testing, simulation, and history.

The P2JB / Patience wait is now a normal flow step (``WAIT FOR LOADER``),
so there is no separate monitor router. These endpoints support the
Advanced-Mode test buttons in the flow builder and surface the
high-level run history rendered in the UI.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

import flow_history
from exec_engine import ExecState, get_exec_state, run_autoload
from models import AutoloadRequest, FlowNotifyTestRequest
import notifications

router = APIRouter()
_log = logging.getLogger("ps5_autopayload")


@router.get("/api/flow/history")
async def api_flow_history():
    return {"runs": flow_history.get_runs()}


@router.delete("/api/flow/history")
async def api_flow_clear_history():
    flow_history.clear_runs()
    return {"success": True}


@router.post("/api/flow/test_notification")
async def api_flow_test_notification(req: FlowNotifyTestRequest):
    """Fire a test notification or simulate the loader-ready event.

    Does not touch the running execution unless ``run_flow=True`` AND
    ``event="simulate_loader_ready"``, in which case the request is
    treated as a real flow start of *flow_name*.
    """
    cfg_dict = req.notify.model_dump()

    if req.event == "simulate_loader_ready":
        # Fire the simulation/notification path first so the user always
        # gets the loader-ready signal, then optionally chain a real flow.
        sim = await notifications.simulate_loader_ready(
            cfg_dict, host=req.host, port=req.port,
        )
        if not req.run_flow:
            return sim
        if not req.flow_name:
            raise HTTPException(400, "run_flow=true requires flow_name")
        if get_exec_state() in (ExecState.RUNNING, ExecState.PAUSED):
            raise HTTPException(409, "A flow is already running")
        flow_name = req.flow_name if req.flow_name.endswith(".txt") else f"{req.flow_name}.txt"
        try:
            result = await run_autoload(AutoloadRequest(
                host=req.host, profile=flow_name, continue_on_error=False,
            ))
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc))
        return {**sim, "ran_flow": True, "flow_result": result}

    try:
        return await notifications.test_notification(
            req.event, cfg_dict,
            host=req.host, port=req.port, flow_name=req.flow_name,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
