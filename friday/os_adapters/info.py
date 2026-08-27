"""Safe, spoken laptop / network facts. No shell."""

from __future__ import annotations

import os
import platform
import socket
import sys
from pathlib import Path


def system_info_reply() -> str:
    host = socket.gethostname() or "unknown"
    user = os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
    system = platform.system() or "Unknown"
    release = platform.release() or ""
    version = platform.version() or ""
    machine = platform.machine() or ""
    py = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    cwd = str(Path.cwd())
    parts = [
        f"This is {system} {release}".strip(),
        f"host {host}",
        f"user {user}",
    ]
    if machine:
        parts.append(f"arch {machine}")
    parts.append(f"Python {py}")
    parts.append(f"folder {cwd}")
    if version and system == "Windows":
        # Keep short; full Windows version string is noisy when spoken.
        build = version.split(".", 1)[0] if version else ""
        if build.isdigit():
            parts.insert(1, f"build {build}")
    return ". ".join(parts) + "."


def network_info_reply(*, check_online: bool = True) -> str:
    host = socket.gethostname() or "unknown"
    local_ip = _primary_ipv4()
    parts = [f"Hostname {host}"]
    if local_ip:
        parts.append(f"local IP {local_ip}")
    else:
        parts.append("no local IPv4 found")
    if check_online:
        parts.append("online" if _is_online() else "offline or blocked")
    return ". ".join(parts) + "."


def _primary_ipv4() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(1.0)
            sock.connect(("8.8.8.8", 80))
            return str(sock.getsockname()[0])
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return ""


def _is_online(host: str = "1.1.1.1", port: int = 443, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
