"""
GitHub API helpers for fetching release assets and downloading payloads.

All functions are synchronous (blocking) – run them via asyncio.run_in_executor.

Detection priority:
  1. Scan repository file tree for .elf / .lua (Git Trees API, single call, cached).
  2. Fall back to release assets if no repo files found – ZIPs are always ignored.
"""
from __future__ import annotations

import io
import json
import time
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

# ── In-memory tree cache ──────────────────────────────────────────
_tree_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
_CACHE_TTL = 300  # seconds


def _gh_get(url: str, timeout: int = 15) -> Any:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


# ── Repo file scanning ────────────────────────────────────────────

def get_repo_folders(owner: str, repo: str) -> List[str]:
    """
    Return top-level directory names in the repository.
    Used to let users select which folder to scan for payloads.
    """
    contents = _gh_get(f"{GITHUB_API}/repos/{owner}/{repo}/contents", timeout=10)
    return sorted(item["name"] for item in contents if item.get("type") == "dir")


def scan_repo_files(
    owner: str, repo: str, folder: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Scan the repository tree for .elf / .lua files using the Git Trees API
    (single recursive call).  Results are cached for _CACHE_TTL seconds.

    If *folder* is given (e.g. "payloads"), only files under that folder are
    returned.  The full tree is always fetched and cached so repeated calls
    with different folder values are cheap.

    Returns a list of:
      { asset_name, path, download_url, sha, tag:"latest", ext, is_zip:False,
        source_type:"repo_file" }
    """
    key = f"{owner}/{repo}"
    now = time.monotonic()
    if key in _tree_cache:
        cached_at, cached = _tree_cache[key]
        if now - cached_at < _CACHE_TTL:
            return _filter_by_folder(cached, folder)

    result = _do_scan_repo_files(owner, repo)
    _tree_cache[key] = (now, result)
    return _filter_by_folder(result, folder)


def _filter_by_folder(
    files: List[Dict[str, Any]], folder: Optional[str]
) -> List[Dict[str, Any]]:
    if not folder:
        return files
    prefix = folder.strip("/") + "/"
    return [f for f in files if f["path"].startswith(prefix)]


def _do_scan_repo_files(owner: str, repo: str) -> List[Dict[str, Any]]:
    # 1. Discover default branch
    repo_info = _gh_get(f"{GITHUB_API}/repos/{owner}/{repo}", timeout=10)
    branch = repo_info.get("default_branch", "main")

    # 2. Full recursive tree in one request
    tree_data = _gh_get(
        f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1",
        timeout=20,
    )

    results: List[Dict[str, Any]] = []
    for item in tree_data.get("tree", []):
        if item.get("type") != "blob":
            continue
        path = item["path"]
        ext = Path(path).suffix.lower()
        if ext not in _PAYLOAD_EXTENSIONS:
            continue
        filename = Path(path).name
        raw_url = (
            f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
        )
        results.append({
            "asset_name":  filename,
            "path":        path,
            "download_url": raw_url,
            "sha":         item.get("sha", ""),
            "tag":         "latest",
            "ext":         ext,
            "is_zip":      False,
            "source_type": "repo_file",
        })
    return results


def invalidate_cache(owner: str, repo: str) -> None:
    _tree_cache.pop(f"{owner}/{repo}", None)


# ── Release assets (ZIP strictly excluded) ────────────────────────

def get_releases(owner: str, repo: str) -> List[Dict[str, Any]]:
    """
    Return all .elf / .lua release assets.  ZIP assets are silently ignored.
    Each entry: { tag, asset_name, download_url, size, ext, is_zip:False,
                  source_type:"release" }
    """
    url = f"{GITHUB_API}/repos/{owner}/{repo}/releases?per_page=100"
    releases = _gh_get(url)

    result: List[Dict[str, Any]] = []
    for rel in releases:
        tag = rel.get("tag_name", "")
        for asset in rel.get("assets", []):
            ext = Path(asset["name"]).suffix.lower()
            if ext not in _PAYLOAD_EXTENSIONS:
                continue          # ZIP and everything else silently skipped
            result.append({
                "tag":          tag,
                "asset_name":   asset["name"],
                "download_url": asset["browser_download_url"],
                "size":         asset.get("size", 0),
                "ext":          ext,
                "is_zip":       False,
                "source_type":  "release",
            })
    return result


# ── Download helpers ──────────────────────────────────────────────

def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": "PS5AutopayloadHA/1.0",
        "Accept": "application/octet-stream",
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def download_payload(url: str, prefer_name: Optional[str] = None) -> Tuple[bytes, str]:
    """
    Download *url* and return (payload_bytes, filename).

    ZIP archives are handled transparently (internal use only – they are never
    surfaced in the UI):
      1. Download into memory
      2. Scan for .elf / .lua
      3. Pick *prefer_name* if present, else first match
    """
    raw = download(url)
    if url.lower().endswith(".zip") or _is_zip(raw):
        return _extract_from_zip(raw, prefer_name)
    filename = prefer_name or Path(url.split("?")[0]).name
    return raw, filename


def _is_zip(data: bytes) -> bool:
    return data[:4] == b"PK\x03\x04"


def _extract_from_zip(data: bytes, prefer_name: Optional[str]) -> Tuple[bytes, str]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        candidates = [
            n for n in zf.namelist()
            if Path(n).suffix.lower() in _PAYLOAD_EXTENSIONS
        ]
        if not candidates:
            raise ValueError("No valid payload (.elf/.lua) found in archive")
        target = next(
            (n for n in candidates if Path(n).name == prefer_name),
            candidates[0],
        )
        return zf.read(target), Path(target).name
