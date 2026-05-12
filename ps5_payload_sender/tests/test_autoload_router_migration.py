"""Tests for the auto-migration that ``/api/autoload/parse`` performs
when an old saved flow still carries per-step loader config on its
``??`` directive.

Spec rule: legacy ``??9021 7200 30 1`` flows should appear in the
builder as a clean marker step + a populated ~notify header, so the
user has a single source of truth. The values get rewritten on the
next save (the builder emits ``??`` alone for new flows).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A TestClient with PROFILES_DIR pointed at a fresh tmp dir."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
    import config as app_config
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    monkeypatch.setattr(app_config, "PROFILES_DIR", profiles)
    # The router imports PROFILES_DIR at import time
    from routers import autoload as autoload_router
    monkeypatch.setattr(autoload_router, "PROFILES_DIR", profiles)
    import main
    return TestClient(main.app), profiles


def test_legacy_wait_for_loader_step_migrates_to_header(client):
    """Old saved flow: ``??9021 7200 30 1`` with no notify header.
    After parse, the step is **gone** from the response, the values
    appear in notify_config, and ``wait_for_loader_enabled`` is on."""
    c, profiles = client
    (profiles / "legacy.txt").write_text(
        "kstuff.elf\n"
        "??9021 7200 30 1\n",
        encoding="utf-8",
    )
    data = c.get("/api/autoload/parse/legacy.txt").json()

    # No wait_for_loader step in the returned step list.
    assert not any(s["type"] == "wait_for_loader" for s in data["steps"])

    cfg = data["notify_config"]
    assert cfg["wait_for_loader_enabled"] is True
    assert cfg["loader_port"]       == 9021
    assert cfg["loader_max_wait_s"] == 7200
    assert cfg["loader_interval_s"] == 30
    # Loader-ready toggle is force-enabled — otherwise the migrated
    # flow would silently wait without notifying.
    assert cfg["loader_ready"] is True


def test_modern_flow_passes_through_unchanged(client):
    """New-style flow has the toggle set in the header and NO ``??``
    step. Parser returns the toggle and no wait_for_loader step."""
    c, profiles = client
    (profiles / "modern.txt").write_text(
        '# ~notify loader_ready=on wait_for_loader_enabled=on '
        'loader_port=9026 loader_interval_s=60 loader_max_wait_s=3600\n'
        'kstuff.elf\n',
        encoding="utf-8",
    )
    data = c.get("/api/autoload/parse/modern.txt").json()
    assert not any(s["type"] == "wait_for_loader" for s in data["steps"])
    cfg = data["notify_config"]
    assert cfg["wait_for_loader_enabled"] is True
    assert cfg["loader_port"]       == 9026
    assert cfg["loader_interval_s"] == 60
    assert cfg["loader_max_wait_s"] == 3600


def test_step_overrides_lose_to_explicit_header(client):
    """If the flow header has an explicit non-default port AND the
    legacy step has its own port, the header wins (don't clobber the
    user's explicit config). Interval / max_wait still get promoted
    from the step because the header was at defaults for those keys."""
    c, profiles = client
    (profiles / "mixed.txt").write_text(
        '# ~notify loader_port=9026\n'
        '??9021 7200 30 1\n',
        encoding="utf-8",
    )
    data = c.get("/api/autoload/parse/mixed.txt").json()
    cfg = data["notify_config"]
    assert cfg["wait_for_loader_enabled"] is True
    assert cfg["loader_port"]       == 9026     # header wins
    assert cfg["loader_max_wait_s"] == 7200     # promoted from step
    assert cfg["loader_interval_s"] == 30
    # Step is dropped from the response either way.
    assert not any(s["type"] == "wait_for_loader" for s in data["steps"])


def test_remote_lua_loader_port_is_first_class(client):
    """Generic loader: 9026 (Remote Lua) round-trips just like 9021."""
    c, profiles = client
    (profiles / "lua.txt").write_text(
        "??9026 1800 15 1\n",
        encoding="utf-8",
    )
    data = c.get("/api/autoload/parse/lua.txt").json()
    cfg = data["notify_config"]
    assert cfg["wait_for_loader_enabled"] is True
    assert cfg["loader_port"]       == 9026
    assert cfg["loader_max_wait_s"] == 1800
    assert cfg["loader_interval_s"] == 15
