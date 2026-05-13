"""Tests for the ZIP-form backup export + import.

User report: previous JSON backup didn't include payload binaries,
so a restore on a fresh add-on install couldn't run any flow until
every payload was re-downloaded from GitHub. Manually uploaded
custom payloads were lost entirely. New format ships the binaries
inside the archive.

Backend must:
* export a ZIP containing `backup.json` + `payloads/*.elf|.lua`
* accept either ZIP or legacy JSON on import (auto-detect via PK
  magic bytes)
* recover the exact same UI / files on a clean instance
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def fresh_install(tmp_path, monkeypatch):
    """A clean storage layout — empty CONFIG_BASE, no payloads, no meta."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
    import config as cfg
    base = tmp_path / "config"
    base.mkdir()
    monkeypatch.setattr(cfg, "CONFIG_BASE",       base)
    monkeypatch.setattr(cfg, "PAYLOAD_DIR",       base / "payloads")
    monkeypatch.setattr(cfg, "PROFILES_DIR",      base / "profiles")
    monkeypatch.setattr(cfg, "STATE_FILE",        base / "config.json")
    monkeypatch.setattr(cfg, "DEVICES_FILE",      base / "devices.json")
    monkeypatch.setattr(cfg, "SOURCES_FILE",      base / "sources.json")
    monkeypatch.setattr(cfg, "PAYLOAD_META_FILE", base / "payload_meta.json")
    monkeypatch.setattr(cfg, "TIMING_FILE",       base / "port_timing.json")
    monkeypatch.setattr(cfg, "FLOW_RUNS_FILE",    base / "flow_runs.json")
    monkeypatch.setattr(cfg, "FLOW_HISTORY_FILE", base / "flow_history.json")
    import storage
    for k in ("CONFIG_BASE", "PAYLOAD_DIR", "PROFILES_DIR", "STATE_FILE",
              "DEVICES_FILE", "SOURCES_FILE", "PAYLOAD_META_FILE"):
        monkeypatch.setattr(storage, k, getattr(cfg, k))
    storage.PAYLOAD_DIR.mkdir(parents=True, exist_ok=True)
    storage.PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    return storage, base


# ── build_backup_zip ─────────────────────────────────────────────


def test_zip_contains_backup_json_and_payload_binaries(fresh_install):
    storage, base = fresh_install
    # Seed: one payload on disk + matching meta + a saved profile
    (storage.PAYLOAD_DIR / "kstuff.elf").write_bytes(b"\x7fELF binary contents")
    (storage.PAYLOAD_DIR / "poops_ps5.lua").write_bytes(b"-- lua source\n")
    storage.save_payload_meta({
        "kstuff.elf": {"repo": "x/y", "asset": "kstuff.elf", "version": "1.0"},
    })
    (storage.PROFILES_DIR / "demo.txt").write_text("kstuff.elf\n", encoding="utf-8")

    blob = storage.build_backup_zip()
    assert blob[:4] == b"PK\x03\x04"
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = set(zf.namelist())
        assert "backup.json" in names
        assert "payloads/kstuff.elf"    in names
        assert "payloads/poops_ps5.lua" in names
        # backup.json carries the meta the user spent time configuring
        meta = json.loads(zf.read("backup.json").decode())
        assert meta["version"] == 1
        assert "kstuff.elf" in meta["payload_meta"]
        assert "demo.txt"  in meta["profiles"]
        # Binary survives exactly
        assert zf.read("payloads/kstuff.elf") == b"\x7fELF binary contents"


def test_zip_skips_bak_files(fresh_install):
    """`.bak` files are rollback artefacts, not user data — leave
    them out of the archive."""
    storage, _ = fresh_install
    (storage.PAYLOAD_DIR / "k.elf").write_bytes(b"x")
    (storage.PAYLOAD_DIR / "k.elf.bak").write_bytes(b"old version")
    blob = storage.build_backup_zip()
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = zf.namelist()
        assert "payloads/k.elf"     in names
        assert "payloads/k.elf.bak" not in names


def test_zip_round_trip_restores_payload_binaries(fresh_install):
    """Build a ZIP, wipe the install, restore from ZIP — payload
    binary lands back on disk byte-for-byte."""
    storage, base = fresh_install
    (storage.PAYLOAD_DIR / "kstuff.elf").write_bytes(b"binary data 12345")
    storage.save_payload_meta({
        "kstuff.elf": {"repo": "x/y", "asset": "kstuff.elf", "version": "1.0"},
    })
    blob = storage.build_backup_zip()

    # Wipe everything
    for f in storage.PAYLOAD_DIR.iterdir():
        f.unlink()
    storage.PAYLOAD_META_FILE.unlink(missing_ok=True)

    backup_dict, payloads = storage.parse_backup_archive(blob)
    assert "kstuff.elf" in payloads
    storage.restore_backup(backup_dict)
    written = storage.restore_backup_payloads(payloads)
    assert written == 1
    assert (storage.PAYLOAD_DIR / "kstuff.elf").read_bytes() == b"binary data 12345"
    assert "kstuff.elf" in storage.load_payload_meta()


# ── parse_backup_archive ─────────────────────────────────────────


def test_parse_archive_accepts_legacy_json(fresh_install):
    """Old `.json` backups must still import — users have them
    sitting around from before the ZIP migration."""
    storage, _ = fresh_install
    legacy = json.dumps({
        "version": 1,
        "state":   {"ps5_ip": "10.0.0.1"},
        "sources": [],
        "payload_meta": {},
        "profiles": {},
    }).encode()
    backup, payloads = storage.parse_backup_archive(legacy)
    assert backup["version"] == 1
    assert payloads == {}


def test_parse_archive_rejects_garbage(fresh_install):
    storage, _ = fresh_install
    with pytest.raises(ValueError):
        storage.parse_backup_archive(b"this is neither a ZIP nor JSON")


def test_parse_archive_rejects_zip_without_backup_json(fresh_install):
    storage, _ = fresh_install
    # Build a ZIP that has only payloads (no backup.json)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("payloads/x.elf", b"x")
    with pytest.raises(ValueError, match="missing backup.json"):
        storage.parse_backup_archive(buf.getvalue())


def test_parse_archive_ignores_non_payload_files(fresh_install):
    """A ZIP that somehow contains arbitrary files (e.g. README) is
    fine — we only extract real payload extensions."""
    storage, _ = fresh_install
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("backup.json", json.dumps({"version": 1}))
        zf.writestr("payloads/x.elf",  b"yes")
        zf.writestr("payloads/junk.txt", b"no")
        zf.writestr("readme.md",         b"no")
    _, payloads = storage.parse_backup_archive(buf.getvalue())
    assert set(payloads.keys()) == {"x.elf"}


# ── HTTP round-trip via the actual router ────────────────────────


@pytest.fixture
def client_with_seed(fresh_install):
    storage, _ = fresh_install
    (storage.PAYLOAD_DIR / "kstuff.elf").write_bytes(b"\x7fELF")
    storage.save_payload_meta({
        "kstuff.elf": {"repo": "x/y", "asset": "kstuff.elf", "version": "1.0"},
    })
    import main
    return TestClient(main.app), storage


def test_get_backup_returns_zip_with_correct_headers(client_with_seed):
    c, _ = client_with_seed
    r = c.get("/api/backup")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    cd = r.headers["content-disposition"]
    assert cd.startswith('attachment; filename="ps5-autopayload-backup-')
    assert cd.endswith('.zip"')
    assert r.content[:4] == b"PK\x03\x04"


def test_inspect_endpoint_returns_preview(client_with_seed):
    c, storage = client_with_seed
    blob = storage.build_backup_zip()
    r = c.post("/api/backup/inspect", content=blob,
               headers={"Content-Type": "application/zip"})
    assert r.status_code == 200
    info = r.json()
    assert info["backup"]["version"] == 1
    assert info["payload_count"] == 1
    assert info["payload_names"]  == ["kstuff.elf"]


def test_restore_zip_round_trip_via_api(client_with_seed):
    c, storage = client_with_seed
    blob = storage.build_backup_zip()
    # Wipe
    (storage.PAYLOAD_DIR / "kstuff.elf").unlink()
    storage.PAYLOAD_META_FILE.unlink(missing_ok=True)
    # Restore via the actual endpoint
    r = c.post("/api/backup/restore", content=blob,
               headers={"Content-Type": "application/zip"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["payloads_restored"] == 1
    assert (storage.PAYLOAD_DIR / "kstuff.elf").read_bytes() == b"\x7fELF"


def test_restore_accepts_legacy_json(client_with_seed):
    c, storage = client_with_seed
    legacy = json.dumps({
        "version": 1,
        "state": {"ps5_ip": "10.0.0.1"},
        "sources": [], "payload_meta": {}, "profiles": {},
    }).encode()
    r = c.post("/api/backup/restore", content=legacy,
               headers={"Content-Type": "application/json"})
    assert r.status_code == 200
    assert r.json()["payloads_restored"] == 0


def test_selective_restore_zip_extracts_only_when_payloads_section_selected(
    client_with_seed,
):
    """User unticks 'Payloads' in the selective import dialog → the
    payload binaries must NOT be written even though they're in the
    ZIP. Same goes for the include_payload_files=0 query param."""
    c, storage = client_with_seed
    blob = storage.build_backup_zip()
    (storage.PAYLOAD_DIR / "kstuff.elf").unlink()
    r = c.post(
        "/api/backup/restore-selective"
        "?sections=sources,flows,profiles,settings&mode=merge&conflict=replace",
        content=blob, headers={"Content-Type": "application/zip"},
    )
    assert r.status_code == 200, r.text
    assert "payloads_restored" not in r.json()
    assert not (storage.PAYLOAD_DIR / "kstuff.elf").exists()
