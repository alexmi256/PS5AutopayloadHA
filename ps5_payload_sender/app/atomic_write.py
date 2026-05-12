"""
Crash-safe file writes.

Plain `Path.write_text(...)` truncates the destination as the first step
and then streams the new content into it. If the process is killed
mid-write (OOM, container restart, SD-card power loss), the file is left
truncated or partial — and because the JSON config files in this add-on
are the only source of truth for sources, devices, payload metadata and
flow history, that corruption costs the user their entire configuration.

`atomic_write_text` / `atomic_write_bytes` write to a sibling `.tmp` file
first and then `os.replace` it onto the destination. `os.replace` is
guaranteed atomic on POSIX (and on Windows since Python 3.3), so any
reader either sees the previous valid file or the new valid file —
never a partial one.

The temp file lives in the same directory as the target so that the
final replace is a rename within one filesystem (cross-FS rename would
silently fall back to copy+unlink, defeating the atomicity).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Union


def _tmp_path(target: Path) -> Path:
    return target.with_name(target.name + ".tmp")


def atomic_write_text(target: Union[Path, str], content: str, encoding: str = "utf-8") -> None:
    target = Path(target)
    tmp = _tmp_path(target)
    tmp.write_text(content, encoding=encoding)
    os.replace(tmp, target)


def atomic_write_bytes(target: Union[Path, str], data: bytes) -> None:
    target = Path(target)
    tmp = _tmp_path(target)
    tmp.write_bytes(data)
    os.replace(tmp, target)
