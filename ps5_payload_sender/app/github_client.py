"""
GitHub API helpers for fetching release assets and downloading payloads.

All functions are synchronous (blocking) – run them via asyncio.run_in_executor.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List

GITHUB_API = "https://api.github.com"
_HEADERS = {
    "User-Agent": "PS5AutopayloadHA/1.0",
    "Accept": "application/vnd.github.v3+json",
}
_PAYLOAD_EXTENSIONS = {".elf", ".lua"}


def get_releases(owner: str, repo: str) -> List[Dict[str, Any]]:
    """
    Return all .elf/.lua release assets from *owner/repo* (up to 100 releases).
    Each entry: {tag, asset_name, download_url, size, ext}
    """
    url = f"{GITHUB_API}/repos/{owner}/{repo}/releases?per_page=100"
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        releases = json.loads(resp.read().decode())

    result: List[Dict[str, Any]] = []
    for rel in releases:
        tag = rel.get("tag_name", "")
        for asset in rel.get("assets", []):
            ext = Path(asset["name"]).suffix.lower()
            if ext in _PAYLOAD_EXTENSIONS:
                result.append({
                    "tag": tag,
                    "asset_name": asset["name"],
                    "download_url": asset["browser_download_url"],
                    "size": asset.get("size", 0),
                    "ext": ext,
                })
    return result


def download(url: str) -> bytes:
    """Download a file from *url* and return its raw bytes."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "PS5AutopayloadHA/1.0",
        "Accept": "application/octet-stream",
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()
