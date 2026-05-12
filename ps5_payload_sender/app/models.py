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
    display_name: str = ""


class ImportPayloadRequest(BaseModel):
    repo: str
    asset_name: str
    download_url: str
    version: str
    all_versions: List[Dict[str, str]] = []   # [{tag, download_url}, ...]
    release_published_at: str = ""
    asset_updated_at: str = ""
    asset_size: int = 0
    release_id: int = 0


class SwitchVersionRequest(BaseModel):
    repo: str
    asset_name: str
    download_url: str
    version: str


class SetDefaultVersionRequest(BaseModel):
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


class SourceUpdateRequest(BaseModel):
    filter: str = ""
    source_type: str = "auto"
    folder: str = ""
    display_name: str = ""


class PatchFlowVersionsRequest(BaseModel):
    filename: str
    version: str


class P2JBMonitorConfig(BaseModel):
    """Configuration for the P2JB / Patience loader-ready monitor."""
    host: str
    elf_port: int = 9021
    lua_port: Optional[int] = None             # None = don't poll LUA
    check_interval: float = 30.0               # seconds between polls
    max_wait: float = 10800.0                  # 3 hours
    auto_run: bool = False                     # run a saved flow when loader ready
    flow_name: Optional[str] = None            # saved-profile name (.txt optional)
    # Notification toggles
    notify_loader_ready: bool = True
    notify_flow_started: bool = False
    notify_flow_completed: bool = True
    notify_flow_failed: bool = True
    # Optional notify.<service> on top of persistent_notification
    notify_service: Optional[str] = None
