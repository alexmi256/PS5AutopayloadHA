from __future__ import annotations

from fastapi import APIRouter

from models import DeviceList
from storage import load_devices, save_devices

router = APIRouter()


@router.get("/api/devices")
async def api_get_devices():
    return {"devices": load_devices()}


@router.post("/api/devices")
async def api_post_devices(req: DeviceList):
    save_devices(req.devices)
    return {"success": True}
