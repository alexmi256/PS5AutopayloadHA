<div align="center">

<img src="logo.png" width="120" alt="PS5 Autopayload Logo"/>

# PS5 Autopayload

### Fully Automated PS5 Payload Execution via Home Assistant

[![Version](https://img.shields.io/badge/version-1.1.0-blue?style=flat-square)](https://github.com/cosmicflow2512/PS5AutopayloadHA)
[![HA](https://img.shields.io/badge/Home%20Assistant-Add--on-41BDF5?style=flat-square&logo=home-assistant)](https://www.home-assistant.io/)
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)

</div>

---

## What is this?

**PS5 Autopayload** is a Home Assistant add-on that fully automates the PS5 payload workflow.

Start your exploit → everything else happens automatically.

---

## Core Idea

This project automates the entire payload chain after a PS5 userland exploit is triggered.

No manual timing. No repeated sending. No trial and error.

---

## How it works

1. You start a userland exploit on your PS5:
   - BD-J (Blu-ray Disc Java)
   - BD-UN-JB
   - Luac0re
   - Game exploits (e.g. Star Wars Racer Revenge)

2. Home Assistant detects that the PS5 is active  
   (e.g. via smart plug power usage)

3. The system monitors specific ports on the PS5

---

## Port Logic (Core System)

- **Port 9026**  
  → Lua Core / Userland Loader is ready  

- **Port 9021**  
  → ELF Loader (elfldr) is ready to receive payloads  

---

## Automated Flow

- Exploit is started (BD-J / Luac0re / Game)
- Home Assistant detects PS5 activity
- Wait for **Port 9026**
- Send **Lua payload**
- Wait for **Port 9021**
- Send **ELF payload**
- Done

---

## What is ELF Loader (elfldr)?

The ELF Loader:

- runs on the PS5 after exploit stage
- listens on **Port 9021**
- receives payloads over the network
- executes them on the system

---

## Important

- This project is **NOT an exploit**
- It does **NOT replace BD-J or Luac0re**
- It only automates the payload execution AFTER the exploit

---

## Features

- Upload `.elf`, `.bin` and `.lua` payloads (including ZIP archives)
- Visual Auto-Load Builder — Send / Delay / Wait-for-Port steps
- Drag-and-drop step reordering
- Export autoload.zip for USB-based delivery
- GitHub Payload Sources — import directly from any public repo
- Automatic update checks for all sources
- Version history per payload (up to 3 versions, auto-pruned)
- Favorites system for payloads and profiles
- Search & filtering (type, name, favorites)
- Quick Start — pin profiles for instant one-tap execution
- Device Manager — save and switch between multiple PS5 IPs
- Config Backup / Restore / Reset with automatic pre-reset backup
- Advanced Mode — toggleable developer tools (Port Checker, Execution Log)
- Persistent configuration — no data loss on restarts or updates
- Run / Stop / Pause / Resume execution
- Real-time state via WebSocket
- Multi-select bulk payload management
- Clean UI optimized for Home Assistant (mobile + desktop)

---

## Screenshots

### Connection
Set your PS5 IP address and manage saved devices.

![Connection](docs/screenshots/connection.png)

---

### Quick Start
Pin your most-used profiles for instant one-tap execution.

![Quick Start](docs/screenshots/quick-start.png)

---

### Payloads
Upload, search, filter and send `.lua` and `.elf` payloads directly to your PS5.

![Payloads](docs/screenshots/payloads.png)

---

### Auto-Load Builder
Build automated payload chains visually — with delays, port waits and reordering.

![Auto-Load Builder](docs/screenshots/builder.png)

---

### Saved Profiles
Manage all your profiles — pin to Quick Start, edit, run or delete.

![Saved Profiles](docs/screenshots/profiles.png)

---

### Port Check
Manually check or wait for a specific port to become available.

![Port Check](docs/screenshots/port-check.png)

---

### Status Log
Live output of every execution step with timestamps and color-coded results.

![Status](docs/screenshots/status.png)

---

## Home Assistant Integration

> **The integration must be installed to use automations, services, and entities.**  
> The add-on alone only provides the web UI — install the integration to unlock HA automation support.

### Setup (one-time)

1. Start the add-on → integration files are written automatically
2. Restart HA Core
3. Go to **Settings → Devices & Services → Add Integration** → search `PS5 Autopayload` → click **Set Up**

No `configuration.yaml` changes needed.

---

### Services

| Service | Parameters | Description |
|---------|-----------|-------------|
| `ps5_autopayload.run_profile` | `profile_name` (dropdown) | Run a saved profile |
| `ps5_autopayload.stop` | — | Stop current execution |
| `ps5_autopayload.pause` | — | Pause at current step |
| `ps5_autopayload.resume` | — | Resume from pause |
| `ps5_autopayload.reload_profiles` | — | Refresh profile dropdown in automations |

> The `profile_name` field shows a **live dropdown** of all your saved profiles in the HA automation editor.

---

### Entities

| Entity | States | Description |
|--------|--------|-------------|
| `sensor.ps5_autopayload_status` | `idle` · `running` · `paused` · `stopped` · `completed` · `failed` | Current execution state |
| `binary_sensor.ps5_autopayload_running` | `on` / `off` | `on` while a profile is active or paused |

---

### Example Automation

Automatically run your payload chain when the PS5 powers on (via smart plug):

```yaml
alias: PS5 Auto Payload on Power
trigger:
  - platform: state
    entity_id: switch.ps5_smart_plug
    to: "on"
condition:
  - condition: state
    entity_id: binary_sensor.ps5_autopayload_running
    state: "off"
action:
  - delay: "00:00:15"   # give PS5 time to boot
  - service: ps5_autopayload.run_profile
    data:
      profile_name: goldhen   # no .txt needed
```

---

## Installation

### Option 1 — Add-on Repository (Recommended)

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store**
2. Click **⋮ → Repositories**
3. Add: `https://github.com/cosmicflow2512/PS5AutopayloadHA`
4. Find **PS5 Autopayload** in the store and click **Install**
5. Start the add-on and open the UI

### Option 2 — Manual Install

```bash
# SSH into your Home Assistant OS
cd /addons
git clone https://github.com/cosmicflow2512/PS5AutopayloadHA ps5autopayload
```

Then: **Settings → Add-ons → Add-on Store → ⋮ → Reload** → install **PS5 Autopayload**.

---

## Configuration

Set in the add-on **Configuration** tab:

```yaml
ps5_ip: "192.168.1.100"   # PS5 IP address (can also be set in the UI)
lua_port: 9026             # Default port for Lua payloads
elf_port: 9021             # Default port for ELF payloads
port_check_timeout: 10     # Seconds to wait for a port before failing
port_check_interval: 500   # Milliseconds between port check retries
```

---

## Auto-Load Profile Syntax

Profiles are plain `.txt` files stored in `/config/ps5_autopayload/profiles/`.  
You can create them visually with the **Builder** or write them by hand:

```
# Comments start with #
exploit.lua              # Send Lua payload (auto port)
exploit.lua 9026         # Send Lua with explicit port
!3000                    # Wait 3000 ms
?9021                    # Wait until port 9021 is open
?9021 90                 # Wait with 90 second timeout
?9021 90 500             # Wait with 90s timeout, check every 500ms
goldhen.elf              # Send ELF payload (auto port)
```

**Example — GoldHen full chain:**
```
# Full GoldHen automation
?9026 120
exploit.lua
?9021 120 500
goldhen.elf
```

---

## UI Overview

| Section | Description |
|---------|-------------|
| **Connection** | Set PS5 IP address and manage saved devices |
| **Quick Start** | Pinned profiles for one-click execution |
| **Payloads** | Upload, manage, and send individual payloads |
| **Auto-Load Builder** | Create and edit automation workflows visually; export as autoload.zip |
| **Saved Profiles** | All profiles with run / edit / delete controls |
| **Payload Sources** | Add GitHub repos as payload sources; import and update payloads |
| **Port Checker** | Manually verify port availability on the PS5 (Advanced Mode) |
| **Execution Log** | Live output from the current or last execution (Advanced Mode) |

---

## Data Storage

All data is stored in the HA config volume — nothing is lost on add-on updates or restarts:

```
/config/ps5_autopayload/
├── payloads/               # .lua and .elf files
├── profiles/               # .txt workflow profiles
├── config.json             # UI state (IP, favorites, settings)
└── ps5_autopayload.log     # Rotating log file

/config/custom_components/ps5_autopayload/
└── ...                     # Auto-generated HA integration (do not edit)
```

---

## Debug & Diagnostics

| Endpoint | Description |
|----------|-------------|
| `GET /api/ha/logs` | Last 200 lines of the log file (`?lines=N` for more) |
| `GET /api/ha/debug` | Test HA Supervisor API connection and token |
| `POST /api/ha/reload-integration` | Refresh profile dropdown + reload HA config entry |

---

## Roadmap

- [ ] Smart Auto Mode (detect PS5 state automatically)
- [ ] Docker standalone version (without Home Assistant)
- [ ] Profile import / export
- [ ] Webhook trigger support

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | FastAPI + uvicorn (Python 3.11) |
| Real-time | WebSocket |
| Payload delivery | TCP socket (binary) |
| Frontend | Vanilla HTML / CSS / JS |
| HA entities | Supervisor Core REST API |
| HA integration | Custom component with Config Flow |

---

## License

MIT — see [LICENSE](LICENSE)

---

<div align="center">
  <sub>Built for Home Assistant · Tested on HA OS · v1.1.0</sub>
</div>
