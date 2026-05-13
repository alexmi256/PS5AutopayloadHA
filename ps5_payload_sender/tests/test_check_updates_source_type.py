"""Tests for /api/sources/check-updates respecting source_type.

User report: a source set to source_type="folder" still triggered
release-based update detection, producing false positives like
"poops_ps5.lua: latest → 2.2d" when 2.2d was a release ZIP (not a
file in the configured folder).

After the fix, folder sources are excluded from the global
update check entirely — the user refreshes them manually via
Edit → Re-scan in the UI.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
    import config as app_config
    monkeypatch.setattr(app_config, "PAYLOAD_META_FILE", tmp_path / "payload_meta.json")
    monkeypatch.setattr(app_config, "SOURCES_FILE",      tmp_path / "sources.json")
    import storage
    monkeypatch.setattr(storage, "PAYLOAD_META_FILE", tmp_path / "payload_meta.json")
    monkeypatch.setattr(storage, "SOURCES_FILE",      tmp_path / "sources.json")
    from routers import sources as sources_router
    monkeypatch.setattr(sources_router, "load_payload_meta",
                        lambda: {"poops_ps5.lua": {
                            "repo": "Gezine/Luac0re", "asset": "poops_ps5.lua",
                            "version": "latest",
                        }})
    yield sources_router


def test_folder_source_uses_tree_not_releases(client, monkeypatch):
    """Source configured as source_type=folder must NOT call
    gh_get_releases — it goes through scan_repo_files and compares
    git blob SHAs against the stored meta.sha."""
    sources_router = client
    monkeypatch.setattr(sources_router, "load_sources", lambda: [{
        "repo": "Gezine/Luac0re", "source_type": "folder", "folder": "payloads",
    }])
    monkeypatch.setattr(sources_router, "load_payload_meta",
                        lambda: {"poops_ps5.lua": {
                            "repo": "Gezine/Luac0re", "asset": "poops_ps5.lua",
                            "version": "latest", "sha": "aaaa1111",
                        }})
    releases_called = {"n": 0}
    monkeypatch.setattr(sources_router, "gh_get_releases",
                        lambda *a: (releases_called.__setitem__("n", releases_called["n"]+1)
                                    or [{"asset_name": "x.zip", "tag": "2.2d",
                                         "download_url": "https://x"}]))
    monkeypatch.setattr(sources_router, "gh_scan_repo_files",
                        lambda owner, repo, folder: [{
                            "asset_name": "poops_ps5.lua",
                            "sha": "aaaa1111",   # same as stored → no update
                            "download_url": "https://raw/poops",
                        }])
    saved = {"called": False}
    monkeypatch.setattr(sources_router, "save_payload_meta",
                        lambda meta: saved.__setitem__("called", True))

    import main
    c = TestClient(main.app)
    r = c.get("/api/sources/check-updates")
    assert r.status_code == 200
    data = r.json()
    assert data["updates"] == []
    assert releases_called["n"] == 0
    assert saved["called"] is False, "no meta write when SHAs already match"


def test_folder_source_detects_sha_change(client, monkeypatch):
    """If the upstream blob SHA differs from the stored SHA, that's
    an update — even though no release tag changed."""
    sources_router = client
    monkeypatch.setattr(sources_router, "load_sources", lambda: [{
        "repo": "Gezine/Luac0re", "source_type": "folder", "folder": "payloads",
    }])
    monkeypatch.setattr(sources_router, "load_payload_meta",
                        lambda: {"poops_ps5.lua": {
                            "repo": "Gezine/Luac0re", "asset": "poops_ps5.lua",
                            "version": "latest", "sha": "aaaa1111",
                        }})
    monkeypatch.setattr(sources_router, "gh_scan_repo_files",
                        lambda owner, repo, folder: [{
                            "asset_name": "poops_ps5.lua",
                            "sha": "bbbb2222deadbeef",
                            "download_url": "https://raw/poops",
                        }])
    monkeypatch.setattr(sources_router, "save_payload_meta", lambda meta: None)

    import main
    c = TestClient(main.app)
    data = c.get("/api/sources/check-updates").json()
    updates = data["updates"]
    assert len(updates) == 1
    assert updates[0]["filename"]        == "poops_ps5.lua"
    assert updates[0]["current_version"] == "aaaa111"     # short SHA
    assert updates[0]["latest_version"]  == "bbbb222"
    assert updates[0]["sha"]             == "bbbb2222deadbeef"


def test_folder_source_backfills_baseline_sha_silently(client, monkeypatch):
    """A folder source whose payloads were imported before SHA
    tracking existed has no `meta.sha`. The first check-updates
    pass must silently backfill the current SHA (no phantom
    "update" reported)."""
    sources_router = client
    monkeypatch.setattr(sources_router, "load_sources", lambda: [{
        "repo": "Gezine/Luac0re", "source_type": "folder", "folder": "payloads",
    }])
    legacy_meta = {"poops_ps5.lua": {
        "repo": "Gezine/Luac0re", "asset": "poops_ps5.lua",
        "version": "latest",
        # NB: no "sha"
    }}
    monkeypatch.setattr(sources_router, "load_payload_meta", lambda: legacy_meta)
    monkeypatch.setattr(sources_router, "gh_scan_repo_files",
                        lambda owner, repo, folder: [{
                            "asset_name": "poops_ps5.lua",
                            "sha": "cccc3333",
                            "download_url": "https://raw/poops",
                        }])
    written = {}
    monkeypatch.setattr(sources_router, "save_payload_meta",
                        lambda meta: written.update(meta))

    import main
    c = TestClient(main.app)
    data = c.get("/api/sources/check-updates").json()
    assert data["updates"] == []      # no phantom update on baseline
    assert written["poops_ps5.lua"]["sha"] == "cccc3333"   # baseline stored


def test_releases_source_still_checked(client, monkeypatch):
    """source_type=releases (or any non-folder) keeps the old behavior."""
    sources_router = client
    monkeypatch.setattr(sources_router, "load_sources", lambda: [{
        "repo": "Gezine/Luac0re", "source_type": "releases",
    }])

    def _fake_releases(owner, repo):
        return [{
            "asset_name": "poops_ps5.lua", "tag": "2.2d",
            "download_url": "https://example/2.2d",
        }]
    monkeypatch.setattr(sources_router, "gh_get_releases", _fake_releases)

    import main
    c = TestClient(main.app)
    r = c.get("/api/sources/check-updates")
    assert r.status_code == 200
    updates = r.json()["updates"]
    assert len(updates) == 1
    assert updates[0]["filename"]        == "poops_ps5.lua"
    assert updates[0]["latest_version"]  == "2.2d"


def test_auto_source_still_checked(client, monkeypatch):
    """source_type='auto' (default for older flows) must also keep
    release-based detection — only 'folder' opts out."""
    sources_router = client
    monkeypatch.setattr(sources_router, "load_sources", lambda: [{
        "repo": "Gezine/Luac0re", "source_type": "auto",
    }])
    called = {"n": 0}
    def _fake_releases(owner, repo):
        called["n"] += 1
        return []
    monkeypatch.setattr(sources_router, "gh_get_releases", _fake_releases)

    import main
    c = TestClient(main.app)
    c.get("/api/sources/check-updates")
    assert called["n"] == 1


def test_missing_source_config_still_checked(client, monkeypatch):
    """If a payload's meta references a repo that's no longer in
    `sources.json` (e.g. user deleted the source but the payload
    file lingers), fall back to the old release-based behavior."""
    sources_router = client
    monkeypatch.setattr(sources_router, "load_sources", lambda: [])
    called = {"n": 0}
    def _fake_releases(owner, repo):
        called["n"] += 1
        return []
    monkeypatch.setattr(sources_router, "gh_get_releases", _fake_releases)

    import main
    c = TestClient(main.app)
    c.get("/api/sources/check-updates")
    assert called["n"] == 1
