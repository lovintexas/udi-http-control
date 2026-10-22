"""Automatic TLS certificate management for HTTP Control."""

import ipaddress
import os
import socket
import subprocess
from pathlib import Path


def get_local_ip():
    """Find the preferred LAN address without sending network traffic."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def ensure_certificate(base_dir):
    """Create a self-signed HTTPS certificate if one is missing."""
    cert_dir = Path(base_dir) / "certs"
    cert_dir.mkdir(mode=0o700, exist_ok=True)

    cert_file = cert_dir / "http-control.crt"
    key_file = cert_dir / "http-control.key"

    if cert_file.is_file() and key_file.is_file():
        return str(cert_file), str(key_file)

    ip = get_local_ip()
    ipaddress.ip_address(ip)

    subprocess.run(
        [
            "openssl", "req",
            "-x509",
            "-newkey", "rsa:2048",
            "-sha256",
            "-nodes",
            "-keyout", str(key_file),
            "-out", str(cert_file),
            "-days", "3650",
            "-subj", f"/CN={ip}/O=HTTP Control",
            "-addext", f"subjectAltName=IP:{ip},DNS:eisy",
        ],
        check=True,
        timeout=30,
    )

    os.chmod(key_file, 0o600)
    os.chmod(cert_file, 0o644)

    return str(cert_file), str(key_file)
