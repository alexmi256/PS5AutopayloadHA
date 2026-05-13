"""Tests for the 'latest_version' label correctness.

User report: shadowmountplus.elf step showed `1.6beta10 (latest)`
even though 1.6test11 was published later. Root cause: the old
`sort_versions` ranked stable > beta > alpha/test by tag-content,
so a beta sorted ahead of a newer test build, and the UI took
`versions[0]` as "latest".

After the fix:
* `sort_versions` ranks by `published_at` desc (date-based)
* `list_payloads` picks the most-recently-published
  entry as latest_version, with a fallback that prefers the
  installed version when no dates are recorded (legacy meta)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def storage_module(tmp_path, monkeypatch):
    """Point storage's payload/meta files at a clean tmp dir + return module."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
    import config as app_config
    payload_dir = tmp_path / "payloads"
    payload_dir.mkdir()
    meta_file = tmp_path / "payload_meta.json"
    monkeypatch.setattr(app_config, "PAYLOAD_DIR",       payload_dir)
    monkeypatch.setattr(app_config, "PAYLOAD_META_FILE", meta_file)
    import storage
    monkeypatch.setattr(storage, "PAYLOAD_DIR",       payload_dir)
    monkeypatch.setattr(storage, "PAYLOAD_META_FILE", meta_file)
    return storage, payload_dir, meta_file


def _make_payload(payload_dir: Path, name: str, content: bytes = b"x"):
    (payload_dir / name).write_bytes(content)


def _write_meta(meta_file: Path, data: dict):
    meta_file.write_text(json.dumps(data), encoding="utf-8")


# ── sort_versions ────────────────────────────────────────────────


def test_sort_versions_orders_by_published_at_desc(storage_module):
    storage, _, _ = storage_module
    out = storage.sort_versions([
        {"tag": "1.6beta10", "published_at": "2026-04-01T00:00:00Z"},
        {"tag": "1.6test11", "published_at": "2026-05-13T00:00:00Z"},  # newer
        {"tag": "1.5",       "published_at": "2026-01-01T00:00:00Z"},
    ])
    assert [v["tag"] for v in out] == ["1.6test11", "1.6beta10", "1.5"]


def test_sort_versions_no_longer_demotes_test_below_beta(storage_module):
    """The old tier-based sort put any 'test' build behind any 'beta'.
    With date-based ranking, a test published AFTER a beta is correctly
    placed first."""
    storage, _, _ = storage_module
    out = storage.sort_versions([
        {"tag": "1.6beta10", "published_at": "2026-04-01T00:00:00Z"},
        {"tag": "1.6test11", "published_at": "2026-05-13T00:00:00Z"},
    ])
    assert out[0]["tag"] == "1.6test11"


def test_sort_versions_preserves_order_without_dates(storage_module):
    """Legacy entries without published_at keep their relative order
    (stable sort) instead of being scrambled."""
    storage, _, _ = storage_module
    out = storage.sort_versions([
        {"tag": "1.6beta10"},
        {"tag": "1.6test11"},
    ])
    assert [v["tag"] for v in out] == ["1.6beta10", "1.6test11"]


# ── list_payloads ('latest_version' label) ─────────────


def test_latest_version_uses_published_at(storage_module):
    storage, payload_dir, meta_file = storage_module
    _make_payload(payload_dir, "shadowmountplus.elf")
    _write_meta(meta_file, {"shadowmountplus.elf": {
        "repo": "drakmor/ShadowMountPlus",
        "asset": "shadowmountplus.elf",
        "version": "1.6test11",
        "versions": [
            {"tag": "1.6beta10", "published_at": "2026-04-01T00:00:00Z"},
            {"tag": "1.6test11", "published_at": "2026-05-13T00:00:00Z"},
        ],
    }})
    result = storage.list_payloads()
    [entry] = [e for e in result if e["name"] == "shadowmountplus.elf"]
    assert entry["source"]["latest_version"] == "1.6test11"


def test_latest_version_legacy_falls_back_to_installed(storage_module):
    """Legacy meta has no published_at on any version entry. Old
    behaviour: latest_version = versions[0]["tag"], which was the
    stable/beta the old sort_versions put first — usually WRONG.
    New behaviour: prefer the installed `version` since the user
    explicitly switched to it. Still imperfect, but unambiguous and
    fixes the visible mislabelling."""
    storage, payload_dir, meta_file = storage_module
    _make_payload(payload_dir, "shadowmountplus.elf")
    _write_meta(meta_file, {"shadowmountplus.elf": {
        "repo": "drakmor/ShadowMountPlus",
        "asset": "shadowmountplus.elf",
        "version": "1.6test11",
        "versions": [
            {"tag": "1.6beta10"},
            {"tag": "1.6test11"},
        ],
    }})
    result = storage.list_payloads()
    [entry] = [e for e in result if e["name"] == "shadowmountplus.elf"]
    assert entry["source"]["latest_version"] == "1.6test11"


def test_latest_version_falls_back_to_versions_first_if_installed_absent(storage_module):
    """If the installed version isn't in versions[] (very edge-case —
    e.g. a manually-copied file), keep versions[0] as the label."""
    storage, payload_dir, meta_file = storage_module
    _make_payload(payload_dir, "foo.elf")
    _write_meta(meta_file, {"foo.elf": {
        "repo": "x/y", "asset": "foo.elf",
        "version": "manual",
        "versions": [{"tag": "1.0"}, {"tag": "1.1"}],
    }})
    result = storage.list_payloads()
    [entry] = [e for e in result if e["name"] == "foo.elf"]
    assert entry["source"]["latest_version"] == "1.0"


def test_latest_version_no_versions_uses_installed(storage_module):
    storage, payload_dir, meta_file = storage_module
    _make_payload(payload_dir, "foo.elf")
    _write_meta(meta_file, {"foo.elf": {
        "repo": "x/y", "asset": "foo.elf",
        "version": "1.0",
        "versions": [],
    }})
    result = storage.list_payloads()
    [entry] = [e for e in result if e["name"] == "foo.elf"]
    assert entry["source"]["latest_version"] == "1.0"
