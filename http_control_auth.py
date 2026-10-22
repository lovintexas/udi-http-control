import base64
import hashlib
import hmac
import os
import secrets
from pathlib import Path

def ensure_credentials(base_dir):
    directory = Path(base_dir) / "data"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "web_auth.txt"
    if path.exists():
        salt, digest = path.read_text().strip().split(":")
        return bytes.fromhex(salt), bytes.fromhex(digest), None

    password = secrets.token_urlsafe(18)
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 300000)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f"{salt.hex()}:{digest.hex()}\n")
    return salt, digest, password

def check_authorization(header, salt, expected):
    if not header or not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:], validate=True).decode()
        username, password = decoded.split(":", 1)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 300000)
        return username == "admin" and hmac.compare_digest(actual, expected)
    except (ValueError, UnicodeError):
        return False
