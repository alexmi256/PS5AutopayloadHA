from __future__ import annotations

import asyncio

from fastapi import APIRouter

from config import SUPERVISOR_TOKEN
from exec_engine import executor, get_exec_state
from ha_client import debug_ha_push, push_ha_state, reload_integration, write_ha_services_yaml

router = APIRouter()


@router.post("/api/ha/push")
async def api_ha_push():
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, push_ha_state, get_exec_state())
    return {"success": True, "state": get_exec_state(), "supervisor_token": bool(SUPERVISOR_TOKEN)}


@router.get("/api/ha/debug")
async def api_ha_debug():
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, debug_ha_push, get_exec_state())


@router.post("/api/ha/reload-integration")
async def api_reload_integration():
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, write_ha_services_yaml)
    return await loop.run_in_executor(executor, reload_integration)
