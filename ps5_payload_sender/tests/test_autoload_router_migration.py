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
    After parse, the step is a clean marker and the values appear in
    the notify_config response."""
    c, profiles = client
    (profiles / "legacy.txt").write_text(
        "kstuff.elf\n"
        "??9021 7200 30 1\n",
        encoding="utf-8",
    )

    r = c.get("/api/autoload/parse/legacy.txt")
    assert r.status_code == 200, r.text
    data = r.json()

    # The step is now a clean marker: zeros across the board.
    wfl = next(s for s in data["steps"] if s["type"] == "wait_for_loader")
    assert wfl["port"]       == 0
    assert wfl["max_wait_s"] == 0
    assert wfl["interval_s"] == 0
    assert wfl["stability_count"] == 1

    # And the values moved into the header.
    cfg = data["notify_config"]
    assert cfg["loader_port"]       == 9021
    assert cfg["loader_max_wait_s"] == 7200
    assert cfg["loader_interval_s"] == 30
    # Loader-ready toggle is force-enabled when we promoted values —
    # without it the migration would be silent.
    assert cfg["loader_ready"] is True


def test_modern_flow_passes_through_unchanged(client):
    """New-style ``??`` (no params) + populated header: values come
    only from the header, the step stays a marker."""
    c, profiles = client
    (profiles / "modern.txt").write_text(
        '# ~notify loader_ready=on loader_port=9026 '
        'loader_interval_s=60 loader_max_wait_s=3600\n'
        '??\n'
        'kstuff.elf\n',
        encoding="utf-8",
    )

    data = c.get("/api/autoload/parse/modern.txt").json()
    wfl = next(s for s in data["steps"] if s["type"] == "wait_for_loader")
    assert (wfl["port"], wfl["max_wait_s"], wfl["interval_s"]) == (0, 0, 0)
    cfg = data["notify_config"]
    assert cfg["loader_port"]       == 9026
    assert cfg["loader_interval_s"] == 60
    assert cfg["loader_max_wait_s"] == 3600


def test_step_overrides_lose_to_explicit_header(client):
    """If a flow already has a non-default header AND legacy step
    overrides, the header wins — we don't clobber the user's explicit
    config. The step keeps its values so the engine still picks them
    up at run time (back-compat)."""
    c, profiles = client
    (profiles / "mixed.txt").write_text(
        '# ~notify loader_port=9026\n'
        '??9021 7200 30 1\n',
        encoding="utf-8",
    )
    data = c.get("/api/autoload/parse/mixed.txt").json()
    cfg = data["notify_config"]
    # Header had loader_port=9026 explicitly — that wins.
    assert cfg["loader_port"] == 9026
    # Step's interval/max were defaults in the header, so they get promoted.
    assert cfg["loader_max_wait_s"] == 7200
    assert cfg["loader_interval_s"] == 30
    # But the port stays on the step so the engine still respects 9021
    # if (somehow) the user runs the unmigrated file directly.
    wfl = next(s for s in data["steps"] if s["type"] == "wait_for_loader")
    assert wfl["port"] == 9021


def test_remote_lua_loader_port_is_first_class(client):
    """Generic loader: 9026 (Remote Lua) round-trips just like 9021."""
    c, profiles = client
    (profiles / "lua.txt").write_text(
        "??9026 1800 15 1\n",
        encoding="utf-8",
    )
    data = c.get("/api/autoload/parse/lua.txt").json()
    cfg = data["notify_config"]
    assert cfg["loader_port"]       == 9026
    assert cfg["loader_max_wait_s"] == 1800
    assert cfg["loader_interval_s"] == 15
