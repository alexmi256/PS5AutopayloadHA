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


class SourceAddRequest(BaseModel):
    repo: str
    filter: str = ""
    source_type: str = "auto"   # "auto" | "releases" | "folder"
    folder: str = ""            # only used when source_type == "folder"


class ImportPayloadRequest(BaseModel):
    repo: str
    asset_name: str
    download_url: str
    version: str
    all_versions: List[Dict[str, str]] = []   # [{tag, download_url}, ...]


class SwitchVersionRequest(BaseModel):
    repo: str
    asset_name: str
    download_url: str
    version: str


class AnalyzePortRequest(BaseModel):
    host: str
    port: int
    timeout: float = 30.0
    interval: float = 0.5


class FlowStepModel(BaseModel):
    type: str                           # 'payload' | 'delay' | 'wait_port'
    # payload fields
    filename: str = ""
    autoPort: int = 0
    portOverride: Optional[int] = None
    # delay fields
    ms: int = 0
    # wait_port fields
    port: int = 0
    timeout: float = 60.0
    interval_ms: int = 500


class FlowAnalyzeRequest(BaseModel):
    host: str
    steps: List[FlowStepModel]
    safe_mode: bool = True
