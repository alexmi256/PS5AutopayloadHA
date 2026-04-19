"""
Autoload file parser for PS5 Payload Sender.

Syntax (one directive per line):
  # comment                          – ignored
  filename.lua [port]                – send payload (port optional)
  filename.elf [port]                – send payload (port optional)
  !<ms>                              – delay in milliseconds
  ?<port>                            – wait until port is reachable
  ?<port> <timeout_seconds>          – wait with custom timeout
  ?<port> <timeout_seconds> <interval_ms>  – wait with custom timeout and poll interval
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union


@dataclass
class SendDirective:
    filename: str
    port: Optional[int] = None


@dataclass
class DelayDirective:
    milliseconds: int


@dataclass
class WaitPortDirective:
    port: int
    timeout_seconds: float = 60.0
    interval_ms: int = 500   # poll interval in milliseconds


Directive = Union[SendDirective, DelayDirective, WaitPortDirective]

_PAYLOAD_RE = re.compile(
    r'^(?P<name>.+?\.(lua|elf))\s*(?P<port>\d+)?$',
    re.IGNORECASE
)

_VERSION_PIN_RE = re.compile(r'^#\s*~version\s+(\S+)\s+(\S+)\s*$')


def parse_version_pins(content: str) -> dict:
    """Return {filename: version_tag} for all ~version annotations in a flow file."""
    pins: dict = {}
    for line in content.splitlines():
        m = _VERSION_PIN_RE.match(line.strip())
        if m:
            pins[m.group(1)] = m.group(2)
    return pins


def set_version_pin(content: str, filename: str, version: str) -> str:
    """Set or replace the ~version annotation for *filename* in *content*."""
    pin_line = f'# ~version {filename} {version}'
    lines = content.splitlines(keepends=True)
    for i, line in enumerate(lines):
        m = _VERSION_PIN_RE.match(line.strip())
        if m and m.group(1) == filename:
            lines[i] = pin_line + ('\n' if line.endswith('\n') else '')
            return ''.join(lines)
    # Not found: insert before the first non-comment, non-empty line
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            lines.insert(i, pin_line + '\n')
            return ''.join(lines)
    return ''.join(lines) + pin_line + '\n'


def parse_line(line: str) -> Optional[Directive]:
    line = line.strip()
    if not line or line.startswith('#'):
        return None

    if line.startswith('!'):
        try:
            ms = int(line[1:].strip())
        except ValueError:
            return None
        return DelayDirective(milliseconds=max(0, ms))

    if line.startswith('?'):
        rest = line[1:].strip().split()
        if not rest:
            return None
        try:
            port = int(rest[0])
        except ValueError:
            return None
        timeout = 60.0
        interval_ms = 500
        if len(rest) >= 2:
            try:
                timeout = float(rest[1])
            except ValueError:
                pass
        if len(rest) >= 3:
            try:
                interval_ms = max(100, int(rest[2]))
            except ValueError:
                pass
        return WaitPortDirective(port=port, timeout_seconds=timeout, interval_ms=interval_ms)

    m = _PAYLOAD_RE.match(line)
    if m:
        name = m.group('name').strip()
        port_str = m.group('port')
        port = int(port_str) if port_str else None
        return SendDirective(filename=name, port=port)

    return None


def parse_autoload_file(content: str) -> List[Directive]:
    directives: List[Directive] = []
    for line in content.splitlines():
        directive = parse_line(line)
        if directive is not None:
            directives.append(directive)
    return directives


def parse_autoload_path(path: Path) -> List[Directive]:
    return parse_autoload_file(path.read_text(encoding="utf-8", errors="replace"))
