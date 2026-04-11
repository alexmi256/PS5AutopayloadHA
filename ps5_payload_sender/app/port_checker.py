"""TCP port availability checker for PS5 Payload Sender."""

import asyncio
import socket
from typing import Optional


async def check_port(
    host: str,
    port: int,
    timeout: float = 2.0
) -> bool:
    """
    Check if a TCP port is reachable on the given host.

    Returns True if a connection can be established, False otherwise.
    """
    try:
        conn = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(conn, timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
        return False


async def wait_for_port(
    host: str,
    port: int,
    total_timeout: float = 60.0,
    interval: float = 0.5,
    connect_timeout: float = 2.0,
    progress_callback=None
) -> bool:
    """
    Poll a TCP port until it becomes reachable or total_timeout expires.

    Args:
        host: Target host/IP
        port: Target port
        total_timeout: Maximum seconds to wait overall
        interval: Seconds between each poll attempt
        connect_timeout: Timeout per individual connection attempt
        progress_callback: Optional async callable(elapsed, total) for status updates

    Returns:
        True if port became reachable within timeout, False otherwise.
    """
    elapsed = 0.0
    while elapsed < total_timeout:
        if await check_port(host, port, timeout=connect_timeout):
            return True
        if progress_callback:
            try:
                await progress_callback(elapsed, total_timeout)
            except Exception:
                pass
        await asyncio.sleep(interval)
        elapsed += interval
    return False
