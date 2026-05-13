"""Pydantic request/response models."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, field_validator


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
    """Builder-side flow step. ``type`` selects which fields are used.

    Supported step types:
      ``payload`` ........ send a payload file
      ``delay`` .......... sleep N ms
      ``wait_port`` ...... short wait until a TCP port is reachable
      ``notify`` ......... emit a free-form notification

    (The legacy ``wait_for_loader`` step type was replaced by the
    flow-level ``wait_for_loader_enabled`` header toggle. Saved
    profiles that still carry a ``??`` directive get migrated to the
    new model on load — see ``routers/autoload.py``.)
    """
    type: str
    # payload
    filename: str = ""
    autoPort: int = 0
    portOverride: Optional[int] = None
    # delay
    ms: int = 0
    # wait_port
    port: int = 0
    timeout: float = 60.0
    interval_ms: int = 500
    # notify
    title: str = ""
    message: str = ""
    service_override: Optional[str] = None


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


class FlowNotifyConfig(BaseModel):
    """Per-flow notification preferences (matches the ``# ~notify …``
    header in the saved profile)."""
    # Event toggles
    loader_ready:            bool = True
    flow_started:            bool = False
    flow_completed:          bool = True
    flow_failed:             bool = True
    # Delivery
    service:                 str  = ""      # must start with "notify." if set
    persistent:              bool = True    # HA notification center
    # Loader-watch master switch (replaces the WAIT FOR LOADER step)
    wait_for_loader_enabled: bool = False
    # Loader-watch config (also used as defaults for legacy ?? directives)
    loader_port:             int  = 9021
    loader_interval_s:       int  = 30
    loader_max_wait_s:       int  = 10800   # 3 h

    @field_validator("service")
    @classmethod
    def _service_must_start_with_notify(cls, v: str) -> str:
        v = (v or "").strip()
        if v and not v.startswith("notify."):
            raise ValueError("notify service must start with 'notify.'")
        return v

    @field_validator("loader_port")
    @classmethod
    def _port_in_range(cls, v: int) -> int:
        if not (1 <= int(v) <= 65535):
            raise ValueError("loader_port must be between 1 and 65535")
        return int(v)

    @field_validator("loader_interval_s")
    @classmethod
    def _interval_min(cls, v: int) -> int:
        if int(v) < 5:
            raise ValueError("loader_interval_s must be at least 5 seconds")
        return int(v)

    @field_validator("loader_max_wait_s")
    @classmethod
    def _max_wait_min(cls, v: int) -> int:
        if int(v) < 60:
            raise ValueError("loader_max_wait_s must be at least 60 seconds (1 minute)")
        return int(v)


class FlowNotifyTestRequest(BaseModel):
    """Body for /api/flow/test_notification (Advanced Mode tools).

    ``event`` ∈ ``{persistent, service, loader_ready, flow_started,
    flow_completed, flow_failed, simulate_loader_ready}``.
    For ``simulate_loader_ready`` the optional ``run_flow`` field
    indicates whether the user opted to also run *flow_name* for real.
    """
    event: str
    notify: FlowNotifyConfig = FlowNotifyConfig()
    host: str = ""
    port: int = 9021
    flow_name: str = ""
    run_flow: bool = False
