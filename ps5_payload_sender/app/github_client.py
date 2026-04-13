"""
GitHub API helpers for fetching release assets and downloading payloads.

All functions are synchronous (blocking) – run them via asyncio.run_in_executor.
Supports .elf / .lua directly and .zip archives (auto-extracts payload files).
"""
from __future__ import annotations

import io
import json
import urllib.request
import urllib.error
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

GITHUB_API = "https://api.github.com"
_HEADERS = {
    "User-Agent": "PS5AutopayloadHA/1.0",
    "Accept": "application/vnd.github.v3+json",
}
_PAYLOAD_EXTENSIONS = {".elf", ".lua"}


def get_releases(owner: str, repo: str) -> List[Dict[str, Any]]:
    """
    Return all .elf/.lua (and .zip) release assets from *owner/repo*.
    Each entry: {tag, asset_name, download_url, size, ext, is_zip}
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
                    "is_zip": False,
                })
            elif ext == ".zip":
                result.append({
                    "tag": tag,
                    "asset_name": asset["name"],
                    "download_url": asset["browser_download_url"],
                    "size": asset.get("size", 0),
                    "ext": ext,
                    "is_zip": True,
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


def download_payload(url: str, prefer_name: Optional[str] = None) -> Tuple[bytes, str]:
    """
    Download *url* and return (payload_bytes, filename).

    If the URL points to a .zip:
      1. Download zip into memory
      2. Scan for .elf / .lua files
      3. Pick *prefer_name* if present, otherwise the first match
      4. Return its bytes + name (zip is never stored)

    Raises ValueError if no valid payload found in archive.
    """
    raw = download(url)

    if url.lower().endswith(".zip") or _is_zip(raw):
        return _extract_from_zip(raw, prefer_name)

    # Plain payload file – derive filename from URL
    filename = prefer_name or Path(url.split("?")[0]).name
    return raw, filename


def _is_zip(data: bytes) -> bool:
    return data[:4] == b"PK\x03\x04"


def _extract_from_zip(data: bytes, prefer_name: Optional[str]) -> Tuple[bytes, str]:
    """Extract the first (or preferred) .elf/.lua file from a zip archive."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        candidates = [
            n for n in zf.namelist()
            if Path(n).suffix.lower() in _PAYLOAD_EXTENSIONS
        ]
        if not candidates:
            raise ValueError("No valid payload (.elf/.lua) found in archive")

        # Prefer exact name match
        target = next(
            (n for n in candidates if Path(n).name == prefer_name),
            candidates[0],
        )
        return zf.read(target), Path(target).name
