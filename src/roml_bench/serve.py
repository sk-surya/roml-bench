"""Minimal static-site server for the generated benchmark report."""

from __future__ import annotations

import functools
import http.server
import ipaddress
import socket
import subprocess
from pathlib import Path


def _local_ips() -> list[str]:
    """Best-effort non-loopback IPv4 addresses without third-party deps."""
    ips: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            addr = info[4][0]
            try:
                ip = ipaddress.ip_address(addr)
            except ValueError:
                continue
            if not ip.is_loopback and str(addr) not in ips:
                ips.append(str(addr))
    except socket.gaierror:
        pass
    # UDP-socket trick reveals the default-route source address.
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            addr = sock.getsockname()[0]
            if addr and addr not in ips and not addr.startswith("127."):
                ips.append(addr)
        finally:
            sock.close()
    except OSError:
        pass
    return ips


def _tailscale_ip() -> str | None:
    try:
        out = subprocess.run(
            ["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=10
        )
        if out.returncode == 0:
            first = out.stdout.strip().splitlines()
            if first:
                return first[0].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def discovery_urls(port: int) -> dict[str, list[str] | str | None]:
    lan = [f"http://{ip}:{port}/" for ip in _local_ips()]
    tailscale = _tailscale_ip()
    return {
        "localhost": f"http://127.0.0.1:{port}/",
        "lan": lan,
        "tailscale": f"http://{tailscale}:{port}/" if tailscale else None,
    }


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:  # keep service logs quiet
        pass


def serve_forever(host: str, port: int, directory: str | Path) -> None:
    root = Path(directory).resolve()
    handler = functools.partial(_QuietHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer((host, port), handler)
    urls = discovery_urls(server.server_address[1])
    print(f"serving {root} on {host}:{port}")
    print(f"localhost: {urls['localhost']}")
    for url in urls["lan"]:
        print(f"lan: {url}")
    if urls["tailscale"]:
        print(f"tailscale: {urls['tailscale']}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
