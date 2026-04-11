"""
PS5 Payload Sender – FastAPI backend (v3.11)
"""

from __future__ import annotations

import asyncio
import json
import logging
import logging.handlers
import os
import shutil
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import aiofiles
from fastapi import (
    FastAPI,
    File,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

from autoload_parser import (
    DelayDirective,
    SendDirective,
    WaitPortDirective,
    parse_autoload_path,
)
from payload_sender import (
    DEFAULT_ELF_PORT,
    DEFAULT_LUA_PORT,
    PAYLOAD_DIR,
    resolve_port,
    send_payload,
)
from port_checker import check_port, wait_for_port

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HOST = os.environ.get("PS5_IP", "")
PORT_CHECK_TIMEOUT = float(os.environ.get("PORT_CHECK_TIMEOUT", 10))
PORT_CHECK_INTERVAL = float(int(os.environ.get("PORT_CHECK_INTERVAL", 500)) / 1000)
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
STATIC_DIR = Path(__file__).parent / "static"
APP_DIR = Path("/app")
GITHUB_RAW_CONFIG = "https://raw.githubusercontent.com/cosmicflow2512/PS5AutopayloadHA/main/ps5_payload_sender/config.yaml"
APP_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Logging – file + stream, auto-rotate at 2 MB, keep 3 backups
# ---------------------------------------------------------------------------

def _setup_logging() -> logging.Logger:
    _log_dir = Path("/config/ps5_autopayload")
    _log_dir.mkdir(parents=True, exist_ok=True)
    _log_file = _log_dir / "ps5_autopayload.log"

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = logging.handlers.RotatingFileHandler(
        _log_file, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    sh.setLevel(logging.INFO)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    if not root.handlers:          # avoid duplicate handlers on hot-reload
        root.addHandler(fh)
        root.addHandler(sh)

    return logging.getLogger("ps5_autopayload")

_log = _setup_logging()

# ---------------------------------------------------------------------------
# Persistent storage – /config/ps5_autopayload/ (survives updates)
# ---------------------------------------------------------------------------

CONFIG_BASE   = Path("/config/ps5_autopayload")
PAYLOAD_DIR   = CONFIG_BASE / "payloads"    # .lua / .elf files
PROFILES_DIR  = CONFIG_BASE / "profiles"   # .txt autoload profiles
STATE_FILE    = CONFIG_BASE / "config.json"
DEVICES_FILE  = CONFIG_BASE / "devices.json"

# Old locations (for one-time migration from /data/)
_OLD_PAYLOAD_DIR  = Path("/data/payloads")
_OLD_STATE_FILE   = Path("/data/state.json")
_OLD_DEVICES_FILE = Path("/data/devices.json")

def _setup_storage() -> None:
    """Create directories and migrate data from legacy /data/ location."""
    CONFIG_BASE.mkdir(parents=True, exist_ok=True)
    PAYLOAD_DIR.mkdir(exist_ok=True)
    PROFILES_DIR.mkdir(exist_ok=True)

    # One-time migration from /data/payloads/
    if _OLD_PAYLOAD_DIR.exists():
        for f in _OLD_PAYLOAD_DIR.iterdir():
            if not f.is_file():
                continue
            ext = f.suffix.lower()
            if ext in {".lua", ".elf"}:
                dest = PAYLOAD_DIR / f.name
            elif ext == ".txt":
                dest = PROFILES_DIR / f.name
            else:
                continue
            if not dest.exists():
                dest.write_bytes(f.read_bytes())

    # One-time migration of state and devices
    if _OLD_STATE_FILE.exists() and not STATE_FILE.exists():
        STATE_FILE.write_bytes(_OLD_STATE_FILE.read_bytes())
    if _OLD_DEVICES_FILE.exists() and not DEVICES_FILE.exists():
        DEVICES_FILE.write_bytes(_OLD_DEVICES_FILE.read_bytes())

    # Remove legacy default profiles
    for name in ("ftp.txt", "goldhen.txt"):
        for d in (PAYLOAD_DIR, PROFILES_DIR):
            p = d / name
            if p.exists():
                p.unlink()

    _write_custom_component()


def _write_custom_component() -> None:
    """Auto-generate HA custom component with GUI config flow."""
    cc_dir = Path("/config/custom_components/ps5_autopayload")
    manifest_path = cc_dir / "manifest.json"

    # Always ensure icon is present (independent of version check)
    cc_dir.mkdir(parents=True, exist_ok=True)
    _icon_src = APP_DIR / "icon.png"
    if _icon_src.exists():
        shutil.copy2(_icon_src, cc_dir / "icon.png")          # HA < 2026.3
        brand_dir = cc_dir / "brand"
        brand_dir.mkdir(exist_ok=True)
        shutil.copy2(_icon_src, brand_dir / "icon.png")       # HA 2026.3+

    # Only rewrite component files when version changes (avoid unnecessary HA reloads)
    current_manifest: dict = {}
    if manifest_path.exists():
        try:
            current_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    if current_manifest.get("version") == APP_VERSION:
        return  # already up-to-date

    first_install = not manifest_path.exists()
    (cc_dir / "translations").mkdir(exist_ok=True)

    # ── manifest.json ──────────────────────────────────────────────
    manifest_path.write_text(json.dumps({
        "domain": "ps5_autopayload",
        "name": "PS5 Autopayload",
        "version": APP_VERSION,
        "documentation": "https://github.com/cosmicflow2512/PS5AutopayloadHA",
        "dependencies": [],
        "codeowners": [],
        "requirements": [],
        "iot_class": "local_push",
        "config_flow": True,
    }, indent=2), encoding="utf-8")

    # ── __init__.py ────────────────────────────────────────────────
    # services.yaml is written by the add-on backend on startup/profile changes,
    # so the dropdown is always populated correctly when HA loads the integration.
    (cc_dir / "__init__.py").write_text(
        '"""PS5 Autopayload – auto-generated HA integration (v' + APP_VERSION + ')."""\n'
        'from __future__ import annotations\n'
        'import logging\n'
        'import aiohttp\n'
        'import voluptuous as vol\n'
        'from homeassistant.config_entries import ConfigEntry\n'
        'from homeassistant.core import HomeAssistant, ServiceCall\n'
        'import homeassistant.helpers.config_validation as cv\n'
        '\n'
        '_LOGGER = logging.getLogger(__name__)\n'
        'DOMAIN = "ps5_autopayload"\n'
        '_ADDON_BASES = ["http://localhost:8765", "http://172.30.32.1:8765"]\n'
        '\n'
        'async def _call(path: str, data: dict | None = None) -> dict:\n'
        '    for base in _ADDON_BASES:\n'
        '        try:\n'
        '            to = aiohttp.ClientTimeout(total=60)\n'
        '            async with aiohttp.ClientSession(timeout=to) as s:\n'
        '                if data is not None:\n'
        '                    async with s.post(f"{base}{path}", json=data) as r:\n'
        '                        return await r.json()\n'
        '                async with s.post(f"{base}{path}") as r:\n'
        '                    return await r.json()\n'
        '        except Exception:\n'
        '            continue\n'
        '    _LOGGER.warning("PS5 Autopayload: add-on unreachable at %s", path)\n'
        '    return {}\n'
        '\n'
        'async def _get(path: str) -> dict:\n'
        '    for base in _ADDON_BASES:\n'
        '        try:\n'
        '            to = aiohttp.ClientTimeout(total=10)\n'
        '            async with aiohttp.ClientSession(timeout=to) as s:\n'
        '                async with s.get(f"{base}{path}") as r:\n'
        '                    return await r.json()\n'
        '        except Exception:\n'
        '            continue\n'
        '    return {}\n'
        '\n'
        'async def async_setup(hass: HomeAssistant, config: dict) -> bool:\n'
        '    return True\n'
        '\n'
        'async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:\n'
        '    async def run_profile(call: ServiceCall) -> None:\n'
        '        profile = call.data["profile_name"].strip()\n'
        '        if not profile.lower().endswith(".txt"):\n'
        '            profile += ".txt"\n'
        '        host = call.data.get("host", "")\n'
        '        if not host:\n'
        '            cfg = await _get("/api/config")\n'
        '            host = cfg.get("ps5_ip", "")\n'
        '        if not host:\n'
        '            _LOGGER.error("PS5 Autopayload: no PS5 IP configured")\n'
        '            return\n'
        '        await _call("/api/autoload/run", {\n'
        '            "host": host, "profile": profile, "continue_on_error": False,\n'
        '        })\n'
        '\n'
        '    async def stop(call: ServiceCall) -> None:\n'
        '        await _call("/api/autoload/stop")\n'
        '\n'
        '    async def pause(call: ServiceCall) -> None:\n'
        '        await _call("/api/autoload/pause")\n'
        '\n'
        '    async def resume(call: ServiceCall) -> None:\n'
        '        await _call("/api/autoload/resume")\n'
        '\n'
        '    async def reload_profiles(call: ServiceCall) -> None:\n'
        '        """Write updated services.yaml and reload this config entry."""\n'
        '        result = await _call("/api/ha/reload-integration")\n'
        '        if result.get("success"):\n'
        '            _LOGGER.info("PS5 Autopayload: integration reloaded with fresh profiles")\n'
        '        else:\n'
        '            _LOGGER.warning("PS5 Autopayload: reload failed – %s", result.get("error"))\n'
        '\n'
        '    if not hass.services.has_service(DOMAIN, "run_profile"):\n'
        '        hass.services.async_register(\n'
        '            DOMAIN, "run_profile", run_profile,\n'
        '            schema=vol.Schema({\n'
        '                vol.Required("profile_name"): cv.string,\n'
        '                vol.Optional("host", default=""): cv.string,\n'
        '            }),\n'
        '        )\n'
        '        hass.services.async_register(DOMAIN, "stop",   stop)\n'
        '        hass.services.async_register(DOMAIN, "pause",  pause)\n'
        '        hass.services.async_register(DOMAIN, "resume", resume)\n'
        '        hass.services.async_register(DOMAIN, "reload_profiles", reload_profiles)\n'
        '        _LOGGER.info("PS5 Autopayload services registered (v' + APP_VERSION + ')")\n'
        '    return True\n'
        '\n'
        'async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:\n'
        '    for svc in ["run_profile", "stop", "pause", "resume", "reload_profiles"]:\n'
        '        hass.services.async_remove(DOMAIN, svc)\n'
        '    return True\n',
        encoding="utf-8",
    )

    # ── config_flow.py ─────────────────────────────────────────────
    (cc_dir / "config_flow.py").write_text(
        '"""Config flow for PS5 Autopayload – adds integration via HA GUI."""\n'
        'from homeassistant import config_entries\n'
        '\n'
        'DOMAIN = "ps5_autopayload"\n'
        '\n'
        'class PS5AutopayloadConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):\n'
        '    VERSION = 1\n'
        '\n'
        '    async def async_step_user(self, user_input=None):\n'
        '        if user_input is not None:\n'
        '            await self.async_set_unique_id(DOMAIN)\n'
        '            self._abort_if_unique_id_configured()\n'
        '            return self.async_create_entry(title="PS5 Autopayload", data={})\n'
        '        return self.async_show_form(step_id="user")\n',
        encoding="utf-8",
    )

    # ── strings.json + translations/en.json ────────────────────────
    _strings = json.dumps({
        "config": {
            "step": {
                "user": {
                    "title": "PS5 Autopayload",
                    "description": (
                        "Connects to the PS5 Autopayload add-on running on this "
                        "Home Assistant instance. Make sure the add-on is running."
                    ),
                }
            },
            "abort": {
                "already_configured": "PS5 Autopayload is already configured.",
            },
        }
    }, indent=2)
    (cc_dir / "strings.json").write_text(_strings, encoding="utf-8")
    (cc_dir / "translations" / "en.json").write_text(_strings, encoding="utf-8")
    (cc_dir / "translations" / "de.json").write_text(json.dumps({
        "config": {
            "step": {
                "user": {
                    "title": "PS5 Autopayload",
                    "description": (
                        "Verbindet sich mit dem PS5 Autopayload Add-on auf diesem "
                        "Home Assistant. Stelle sicher, dass das Add-on läuft."
                    ),
                }
            },
            "abort": {
                "already_configured": "PS5 Autopayload ist bereits konfiguriert.",
            },
        }
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── services.yaml (backend rewrites on each startup/profile change) ────
    (cc_dir / "services.yaml").write_text(
        'run_profile:\n'
        '  name: Run Profile\n'
        '  description: Execute a saved PS5 Autopayload profile\n'
        '  fields:\n'
        '    profile_name:\n'
        '      name: Profile Name\n'
        '      description: Select or type a profile name (without .txt)\n'
        '      required: true\n'
        '      selector:\n'
        '        text:\n'
        '    host:\n'
        '      name: PS5 IP Override\n'
        '      description: Override PS5 IP (uses add-on config if omitted)\n'
        '      required: false\n'
        '      selector:\n'
        '        text:\n'
        'stop:\n'
        '  name: Stop\n'
        '  description: Stop the current PS5 Autopayload execution\n'
        'pause:\n'
        '  name: Pause\n'
        '  description: Pause the current execution\n'
        'resume:\n'
        '  name: Resume\n'
        '  description: Resume a paused execution\n'
        'reload_profiles:\n'
        '  name: Reload Profiles\n'
        '  description: Refresh the profile dropdown from the add-on\n',
        encoding="utf-8",
    )

    # ── Notification ───────────────────────────────────────────────
    _log.info("Custom component written (v%s) – %s install", APP_VERSION,
              "first" if first_install else "update")
    try:
        msg = (
            "PS5 Autopayload Integration aktualisiert (v" + APP_VERSION + "). "
            "Bitte Home Assistant Core neu starten und dann unter "
            "Einstellungen → Geräte & Dienste → Integration hinzufügen → "
            "\"PS5 Autopayload\" suchen."
            if not first_install else
            "PS5 Autopayload Integration installiert (v" + APP_VERSION + "). "
            "Bitte Home Assistant Core neu starten, dann unter "
            "Einstellungen → Geräte & Dienste → Integration hinzufügen → "
            "\"PS5 Autopayload\" suchen und einrichten."
        )
        data = json.dumps({
            "title": "PS5 Autopayload",
            "message": msg,
            "notification_id": "ps5_autopayload_setup",
        }).encode()
        req = urllib.request.Request(
            "http://supervisor/core/api/services/persistent_notification/create",
            data=data,
            headers={
                "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        _log.warning("Could not send HA notification: %s", e)


_setup_storage()

# Override payload_sender's PAYLOAD_DIR so send_payload finds files
import payload_sender as _ps_module
_ps_module.PAYLOAD_DIR = PAYLOAD_DIR

_executor = ThreadPoolExecutor(max_workers=2)

# ---------------------------------------------------------------------------
# Execution state machine
# ---------------------------------------------------------------------------

class ExecState:
    IDLE      = "idle"
    RUNNING   = "running"
    PAUSED    = "paused"
    STOPPED   = "stopped"
    COMPLETED = "completed"
    FAILED    = "failed"

_exec_state:    str              = ExecState.IDLE
_stop_event:    asyncio.Event    = asyncio.Event()    # set = stop requested
_pause_event:   asyncio.Event    = asyncio.Event()    # set = NOT paused
_run_lock:      asyncio.Lock     = asyncio.Lock()

# Initialize: start unpaused, not stopped
_pause_event.set()

# ---------------------------------------------------------------------------
# HA state push (via Supervisor Core API)
# ---------------------------------------------------------------------------

def _push_ha_state_sync(state_val: str) -> None:
    if not SUPERVISOR_TOKEN:
        _log.debug("HA push skipped – no SUPERVISOR_TOKEN (homeassistant_api: true not set?)")
        return
    is_running = state_val in (ExecState.RUNNING, ExecState.PAUSED)
    entities = [
        (
            "sensor.ps5_autopayload_status",
            state_val,
            {
                "friendly_name": "PS5 Autopayload Status",
                "icon": "mdi:gamepad-variant",
                "version": APP_VERSION,
            },
        ),
        (
            "binary_sensor.ps5_autopayload_running",
            "on" if is_running else "off",
            {
                "friendly_name": "PS5 Autopayload Running",
                "device_class": "connectivity",  # valid HA device_class
                "icon": "mdi:play-circle" if is_running else "mdi:stop-circle",
            },
        ),
    ]
    _log.debug("Pushing HA state '%s' for %d entities", state_val, len(entities))
    for entity_id, val, attrs in entities:
        url = f"http://supervisor/core/api/states/{entity_id}"
        try:
            data = json.dumps({"state": val, "attributes": attrs}).encode()
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                _log.info("HA entity '%s' → '%s' (HTTP %s)", entity_id, val, resp.status)
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:300]
            _log.error("HA push HTTP %s for '%s': %s | body: %s", e.code, entity_id, e.reason, body)
        except urllib.error.URLError as e:
            _log.error("HA push URL error for '%s': %s", entity_id, e.reason)
        except Exception as e:
            _log.exception("HA push unexpected error for '%s': %s", entity_id, e)

async def set_exec_state(state_val: str, profile: str = "") -> None:
    global _exec_state
    _exec_state = state_val
    await manager.broadcast({"type": "exec_state", "state": state_val, "profile": profile})
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(_executor, _push_ha_state_sync, state_val)

# ---------------------------------------------------------------------------
# HA services.yaml – written by backend so dropdown is populated before HA loads
# ---------------------------------------------------------------------------

_HA_HIDDEN = {"ftp.txt", "goldhen.txt", "_builder_run.txt"}

def _write_ha_services_yaml() -> None:
    """Write /config/custom_components/ps5_autopayload/services.yaml with current profiles."""
    cc_dir = Path("/config/custom_components/ps5_autopayload")
    if not (cc_dir / "manifest.json").exists():
        return  # component not installed yet
    profiles: List[str] = []
    if PROFILES_DIR.exists():
        profiles = sorted(
            f.name[:-4]
            for f in PROFILES_DIR.iterdir()
            if f.is_file() and f.suffix.lower() == ".txt" and f.name not in _HA_HIDDEN
        )
    lines: List[str] = [
        "run_profile:\n",
        "  name: Run Profile\n",
        "  description: Execute a saved PS5 Autopayload profile\n",
        "  fields:\n",
        "    profile_name:\n",
        "      name: Profile Name\n",
        "      description: Select a profile (without .txt)\n",
        "      required: true\n",
    ]
    if profiles:
        lines += [
            "      selector:\n",
            "        select:\n",
            "          custom_value: true\n",
            "          options:\n",
        ]
        for p in profiles:
            lines.append(f"          - '{p}'\n")
    else:
        lines += ["      selector:\n", "        text:\n"]
    lines += [
        "    host:\n",
        "      name: PS5 IP Override\n",
        "      description: Override PS5 IP (uses add-on config if omitted)\n",
        "      required: false\n",
        "      selector:\n",
        "        text:\n",
        "stop:\n",
        "  name: Stop\n",
        "  description: Stop the current execution\n",
        "pause:\n",
        "  name: Pause\n",
        "  description: Pause the current execution\n",
        "resume:\n",
        "  name: Resume\n",
        "  description: Resume a paused execution\n",
        "reload_profiles:\n",
        "  name: Reload Profiles\n",
        "  description: Refresh the profile dropdown (then reload integration in HA)\n",
    ]
    (cc_dir / "services.yaml").write_text("".join(lines), encoding="utf-8")
    _log.info("HA services.yaml written with %d profiles", len(profiles))

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="PS5 Autopayload", version=APP_VERSION)

@app.on_event("startup")
async def _on_startup() -> None:
    """Push initial HA states and write services.yaml with current profiles."""
    _log.info("PS5 Autopayload v%s starting up", APP_VERSION)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(_executor, _push_ha_state_sync, ExecState.IDLE)
    await loop.run_in_executor(_executor, _write_ha_services_yaml)
    _log.info("Startup complete")

# ---------------------------------------------------------------------------
# WebSocket manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    def __init__(self) -> None:
        self._active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._active.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._active.discard(ws)

    async def broadcast(self, message: dict) -> None:
        data = json.dumps(message, ensure_ascii=False)
        dead: Set[WebSocket] = set()
        for ws in list(self._active):
            try:
                await ws.send_text(data)
            except Exception:
                dead.add(ws)
        self._active -= dead

    async def status(self, msg: str, level: str = "info", **extra) -> None:
        await self.broadcast({"type": "status", "level": level, "message": msg, **extra})


manager = ConnectionManager()

# ---------------------------------------------------------------------------
# Device storage
# ---------------------------------------------------------------------------

def load_devices() -> List[Dict[str, Any]]:
    try:
        if DEVICES_FILE.exists():
            return json.loads(DEVICES_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []

def save_devices(devices: List[Dict[str, Any]]) -> None:
    DEVICES_FILE.write_text(
        json.dumps(devices, ensure_ascii=False, indent=2), encoding="utf-8"
    )

# ---------------------------------------------------------------------------
# UI state persistence (/data/state.json)
# ---------------------------------------------------------------------------

def load_ui_state() -> dict:
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def save_ui_state(data: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

# ---------------------------------------------------------------------------
# Remote version check
# ---------------------------------------------------------------------------

def _get_remote_version_sync() -> str:
    try:
        req = urllib.request.Request(
            GITHUB_RAW_CONFIG,
            headers={"User-Agent": "PS5PayloadSender/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode()
        for line in content.splitlines():
            if line.strip().startswith("version:"):
                return line.split(":", 1)[1].strip().strip("\"'")
    except Exception:
        pass
    return ""

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALLOWED_PAYLOAD_EXTENSIONS = {".lua", ".elf"}

def list_payloads() -> List[dict]:
    result = []
    for f in sorted(PAYLOAD_DIR.iterdir()):
        if f.is_file() and f.suffix.lower() in ALLOWED_PAYLOAD_EXTENSIONS:
            st = f.stat()
            result.append({
                "name": f.name,
                "size": st.st_size,
                "ext": f.suffix.lower(),
                "auto_port": resolve_port(f.name),
                "mtime": int(st.st_mtime),
            })
    return result

HIDDEN_PROFILES = {"ftp.txt", "goldhen.txt", "_builder_run.txt"}

def list_profiles() -> List[str]:
    return [
        f.name for f in sorted(PROFILES_DIR.iterdir())
        if f.is_file() and f.suffix.lower() == ".txt" and f.name not in HIDDEN_PROFILES
    ]

# ---------------------------------------------------------------------------
# Root – inject ingress base path
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    ingress_path = request.headers.get("X-Ingress-Path", "").rstrip("/")
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    inject = f'<script>window.PS5_BASE="{ingress_path}";</script>'
    html = html.replace("</head>", inject + "\n</head>", 1)
    return HTMLResponse(content=html)

# ---------------------------------------------------------------------------
# API – Version
# ---------------------------------------------------------------------------

@app.get("/api/version")
async def get_version():
    return {"version": APP_VERSION}

@app.get("/api/version/check")
async def check_version():
    loop = asyncio.get_running_loop()
    remote = await loop.run_in_executor(_executor, _get_remote_version_sync)
    up_to_date = (not remote) or (remote == APP_VERSION)
    return {"current": APP_VERSION, "remote": remote, "up_to_date": up_to_date}

# ---------------------------------------------------------------------------
# API – Config
# ---------------------------------------------------------------------------

@app.get("/api/config")
async def get_config():
    return {
        "ps5_ip": HOST,
        "lua_port": DEFAULT_LUA_PORT,
        "elf_port": DEFAULT_ELF_PORT,
        "port_check_timeout": PORT_CHECK_TIMEOUT,
        "port_check_interval": PORT_CHECK_INTERVAL,
    }

# ---------------------------------------------------------------------------
# API – UI State
# ---------------------------------------------------------------------------

@app.get("/api/state")
async def get_state():
    return load_ui_state()

@app.post("/api/state")
async def post_state(request: Request):
    data = await request.json()
    save_ui_state(data)
    return {"success": True}

# ---------------------------------------------------------------------------
# API – Devices
# ---------------------------------------------------------------------------

@app.get("/api/devices")
async def get_devices():
    return {"devices": load_devices()}

@app.post("/api/devices")
async def post_devices(req: DeviceList):
    save_devices(req.devices)
    return {"success": True}

# ---------------------------------------------------------------------------
# API – Payloads
# ---------------------------------------------------------------------------

@app.get("/api/payloads")
async def api_list_payloads():
    return {"payloads": list_payloads()}

@app.post("/api/payloads/upload")
async def api_upload(file: UploadFile = File(...)):
    safe = Path(file.filename).name
    ext = Path(safe).suffix.lower()
    if ext not in ALLOWED_PAYLOAD_EXTENSIONS:
        raise HTTPException(400, f"Type '{ext}' not allowed — only .lua and .elf files")
    content = await file.read()
    async with aiofiles.open(PAYLOAD_DIR / safe, "wb") as f:
        await f.write(content)
    await manager.status(f"'{safe}' uploaded ({len(content)} bytes)", level="success")
    return {"success": True, "filename": safe, "size": len(content), "auto_port": resolve_port(safe)}

@app.delete("/api/payloads/{filename}")
async def api_delete(filename: str):
    p = PAYLOAD_DIR / Path(filename).name
    if not p.exists():
        raise HTTPException(404, "Not found")
    p.unlink()
    return {"success": True}

# ---------------------------------------------------------------------------
# API – Send
# ---------------------------------------------------------------------------

@app.post("/api/send")
async def api_send(req: SendRequest):
    port = resolve_port(req.filename, req.port)
    await manager.status(f"Sending '{req.filename}' → {req.host}:{port} …")
    result = await send_payload(req.host, port, req.filename)
    level = "success" if result["success"] else "error"
    await manager.status(result["message"], level=level)
    return result

# ---------------------------------------------------------------------------
# API – Autoload
# ---------------------------------------------------------------------------

@app.get("/api/autoload/profiles")
async def api_profiles():
    return {"profiles": list_profiles()}

@app.get("/api/autoload/content/{profile}")
async def api_get_content(profile: str):
    p = PROFILES_DIR / Path(profile).name
    if not p.exists():
        raise HTTPException(404, "Profile not found")
    return {"content": p.read_text(encoding="utf-8", errors="replace"), "profile": p.name}

@app.post("/api/autoload/content")
async def api_save_content(req: SaveProfileRequest):
    safe = Path(req.profile).name
    if not safe.endswith(".txt"):
        raise HTTPException(400, "Only .txt files allowed")
    (PROFILES_DIR / safe).write_text(req.content, encoding="utf-8")
    await manager.status(f"Profile '{safe}' saved", level="success")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(_executor, _write_ha_services_yaml)
    return {"success": True}

@app.delete("/api/autoload/content/{profile}")
async def api_delete_profile(profile: str):
    p = PROFILES_DIR / Path(profile).name
    if not p.exists():
        raise HTTPException(404, "Profile not found")
    p.unlink()
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(_executor, _write_ha_services_yaml)
    return {"success": True}

@app.get("/api/autoload/parse/{profile}")
async def api_parse_profile(profile: str):
    p = PROFILES_DIR / Path(profile).name
    if not p.exists():
        raise HTTPException(404, "Profile not found")
    directives = parse_autoload_path(p)
    steps = []
    for d in directives:
        if isinstance(d, SendDirective):
            auto_port = resolve_port(d.filename)
            steps.append({
                "type": "payload",
                "filename": d.filename,
                "autoPort": auto_port,
                "portOverride": d.port,
            })
        elif isinstance(d, DelayDirective):
            steps.append({"type": "delay", "ms": d.milliseconds})
        elif isinstance(d, WaitPortDirective):
            steps.append({"type": "wait_port", "port": d.port, "timeout": d.timeout_seconds, "interval_ms": d.interval_ms})
    return {"steps": steps, "profile": p.name}

@app.get("/api/autoload/state")
async def api_exec_state():
    return {"state": _exec_state}

@app.post("/api/ha/push")
async def api_ha_push():
    """Force-push current state to HA entities (useful for debugging)."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(_executor, _push_ha_state_sync, _exec_state)
    return {"success": True, "state": _exec_state, "supervisor_token": bool(SUPERVISOR_TOKEN)}

@app.get("/api/ha/debug")
async def api_ha_debug():
    """Diagnose HA entity push – returns full error details."""
    token = SUPERVISOR_TOKEN
    results = []
    entity_id = "sensor.ps5_autopayload_status"
    if not token:
        return {
            "supervisor_token": False,
            "error": "SUPERVISOR_TOKEN is empty – add 'homeassistant_api: true' to config.yaml and restart",
        }
    try:
        data = json.dumps({"state": _exec_state, "attributes": {"friendly_name": "PS5 Autopayload Status"}}).encode()
        req = urllib.request.Request(
            f"http://supervisor/core/api/states/{entity_id}",
            data=data,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="PUT",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode()
            results.append({"entity": entity_id, "http_status": resp.status, "response": body[:200]})
    except urllib.error.HTTPError as e:
        results.append({"entity": entity_id, "http_error": e.code, "reason": str(e.reason), "body": e.read().decode()[:200]})
    except Exception as e:
        results.append({"entity": entity_id, "error": str(e)})
    return {
        "supervisor_token": True,
        "token_prefix": token[:8] + "…",
        "current_state": _exec_state,
        "results": results,
    }

@app.get("/api/ha/logs")
async def api_ha_logs(lines: int = 200):
    """Return the last N lines of the add-on log file."""
    log_file = CONFIG_BASE / "ps5_autopayload.log"
    if not log_file.exists():
        return {"lines": [], "error": "Log file not found – add-on may not have written any logs yet"}
    try:
        async with aiofiles.open(log_file, "r", encoding="utf-8", errors="replace") as f:
            content = await f.read()
        all_lines = content.splitlines()
        return {"lines": all_lines[-lines:], "total": len(all_lines)}
    except Exception as e:
        return {"lines": [], "error": str(e)}

@app.post("/api/ha/reload-integration")
async def api_reload_integration():
    """Write services.yaml with current profiles and reload the HA config entry."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(_executor, _write_ha_services_yaml)
    token = SUPERVISOR_TOKEN
    if not token:
        return {"success": False, "error": "No SUPERVISOR_TOKEN"}
    try:
        # Find the ps5_autopayload config entry
        req = urllib.request.Request(
            "http://supervisor/core/api/config/config_entries/entries",
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            entries = json.loads(resp.read().decode())
        entry = next((e for e in entries if e.get("domain") == "ps5_autopayload"), None)
        if not entry:
            return {"success": False, "error": "Integration not set up in HA – add it first"}
        entry_id = entry["entry_id"]
        # Reload the config entry
        data = json.dumps({"entry_id": entry_id}).encode()
        req2 = urllib.request.Request(
            "http://supervisor/core/api/services/homeassistant/reload_config_entry",
            data=data,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req2, timeout=10):
            pass
        _log.info("HA integration reloaded (entry_id=%s)", entry_id)
        return {"success": True, "entry_id": entry_id}
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:200]
        _log.error("HA reload HTTP %s: %s | %s", e.code, e.reason, body)
        return {"success": False, "error": f"HTTP {e.code}: {e.reason}"}
    except Exception as e:
        _log.error("HA reload error: %s", e)
        return {"success": False, "error": str(e)}

@app.post("/api/autoload/stop")
async def api_stop_autoload():
    _stop_event.set()
    _pause_event.set()   # unpause so the loop can see the stop flag
    await manager.status("Stop requested …", level="warn")
    return {"success": True}

@app.post("/api/autoload/pause")
async def api_pause_autoload():
    if _exec_state != ExecState.RUNNING:
        return {"success": False, "message": "Not running"}
    _pause_event.clear()   # clear = paused
    await set_exec_state(ExecState.PAUSED)
    await manager.status("Execution paused ⏸", level="warn")
    return {"success": True}

@app.post("/api/autoload/resume")
async def api_resume_autoload():
    if _exec_state != ExecState.PAUSED:
        return {"success": False, "message": "Not paused"}
    _pause_event.set()     # set = running
    await set_exec_state(ExecState.RUNNING)
    await manager.status("Execution resumed ▶", level="success")
    return {"success": True}

@app.post("/api/autoload/run")
async def api_run_autoload(req: AutoloadRequest):
    # Enforce single execution
    if _run_lock.locked():
        raise HTTPException(409, "An execution is already in progress")

    safe = Path(req.profile).name
    path = PROFILES_DIR / safe
    if not path.exists():
        raise HTTPException(404, "Profile not found")

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
            """Returns True if stop was requested."""
            await _pause_event.wait()
            return _stop_event.is_set()

        for i, d in enumerate(directives, 1):
            if await _check_stop_pause():
                stopped = True
                await manager.status("■ Stopped", level="warn")
                break

            if isinstance(d, SendDirective):
                port = resolve_port(d.filename, d.port)
                await manager.status(f"[{i}/{len(directives)}] Sending '{d.filename}' → {req.host}:{port}")
                r = await send_payload(req.host, port, d.filename)
                results.append(r)
                await manager.status(r["message"], level="success" if r["success"] else "error")
                if not r["success"] and not req.continue_on_error:
                    aborted = True; break

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
                    stopped = True; break

            elif isinstance(d, WaitPortDirective):
                interval_s = max(0.1, d.interval_ms / 1000)
                await manager.status(
                    f"[{i}/{len(directives)}] Waiting for port {d.port} (max {d.timeout_seconds}s, every {d.interval_ms}ms) …",
                    waiting_port=d.port,
                )
                loop_start = asyncio.get_running_loop().time()
                reached = False
                while True:
                    if _stop_event.is_set():
                        stopped = True; break
                    await _pause_event.wait()
                    ok = await check_port(req.host, d.port, timeout=2.0)
                    if ok:
                        await manager.status(f"Port {d.port} reachable!", level="success")
                        reached = True; break
                    elapsed = asyncio.get_running_loop().time() - loop_start
                    if elapsed >= d.timeout_seconds:
                        break
                    await manager.status(
                        f"Waiting for port {d.port} … ({elapsed:.0f}/{d.timeout_seconds:.0f}s)",
                        waiting_port=d.port,
                    )
                    # Sleep in 100ms chunks for responsiveness
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
                        aborted = True; break

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
            summary = "Completed ✓" if all_ok else "Completed with errors"
            level   = "success" if all_ok else "error"
            final_state = ExecState.COMPLETED if all_ok else ExecState.FAILED

        await manager.status(summary, level=level)
        await set_exec_state(final_state, profile=safe)
        # Reset to idle after a short delay so UI can display the final state
        await asyncio.sleep(2)
        await set_exec_state(ExecState.IDLE)

        return {"success": not aborted and not stopped, "aborted": aborted, "stopped": stopped, "steps": len(directives)}

# ---------------------------------------------------------------------------
# API – Port check
# ---------------------------------------------------------------------------

@app.post("/api/port/check")
async def api_check_port(req: PortCheckRequest):
    ok = await check_port(req.host, req.port, timeout=req.timeout)
    return {"reachable": ok, "host": req.host, "port": req.port}

@app.post("/api/port/wait")
async def api_wait_port(req: PortCheckRequest):
    await manager.status(
        f"Waiting for port {req.port} on {req.host} (max {req.timeout}s) …",
        waiting_port=req.port,
    )
    async def _prog(elapsed, total):
        await manager.status(
            f"Waiting for port {req.port} … ({elapsed:.0f}/{total:.0f}s)",
            waiting_port=req.port,
        )
    ok = await wait_for_port(
        req.host, req.port,
        total_timeout=req.timeout, interval=req.interval,
        connect_timeout=2.0, progress_callback=_prog,
    )
    msg = f"Port {req.port} reachable!" if ok else f"Timeout: port {req.port} not reachable"
    await manager.status(msg, level="success" if ok else "error")
    return {"reachable": ok, "host": req.host, "port": req.port}

# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await manager.connect(ws)
    await ws.send_text(json.dumps({
        "type": "config",
        "ps5_ip": HOST,
        "lua_port": DEFAULT_LUA_PORT,
        "elf_port": DEFAULT_ELF_PORT,
    }))
    try:
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await ws.send_text(json.dumps({"type": "pong"}))
            except Exception:
                pass
    except WebSocketDisconnect:
        manager.disconnect(ws)

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8765, log_level="info", access_log=False)
