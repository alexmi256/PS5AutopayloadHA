"""Pydantic request/response models."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class SendRequest(BaseModel):
    host: str
    port: Optional[int] = None
    filename: str


class AutoloadRequest(BaseModel):
    host: str
    profile: str
    continue_on_error: bool = False


class SaveProfileRequest(BaseModel):
    profile: str
    content: str


class PortCheckRequest(BaseModel):
    host: str
    port: int
    timeout: float = 5.0
    interval: float = 0.5


class DeviceList(BaseModel):
    devices: List[Dict[str, Any]]
