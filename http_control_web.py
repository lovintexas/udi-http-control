#!/usr/bin/env python3
import ssl
from http_control_tls import ensure_certificate
from http_control_sessions import (
    create_session,
    validate_session,
    destroy_session,
    destroy_all_sessions,
    login_allowed,
    record_login_failure,
    clear_login_failures,
)
from http_control_auth import (
    check_password,
    read_credentials,
    create_initial_password,
    change_password,
    complete_recovery,
    recovery_path,
)

import html
import json
import os
import tempfile
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


AUTH_LOCK = threading.RLock()
AUTH_BASE = Path(__file__).resolve().parent


IDENTITY_FILE = AUTH_BASE / "data/http_control_identity.json"


def plugin_api_path(endpoint):
    identity = json.loads(IDENTITY_FILE.read_text())
    slot = str(identity.get("profileNum", ""))

    if not slot.isdigit() or int(slot) < 1:
        raise ValueError("Invalid HTTP_Control plugin slot")

    return f"/api/plugin/{slot}/{endpoint}"



_config_sync = None
_config_polyglot = None


def bind_config_sync(sync, polyglot):
    global _config_sync, _config_polyglot
    _config_sync = sync
    _config_polyglot = polyglot


def write_eisy_customparams(params):
    if _config_sync is None or _config_polyglot is None:
        raise RuntimeError("PG3x configuration bridge not initialized")

    confirmed = _config_sync.save(_config_polyglot, params)
    return {"successful": True, "data": confirmed}


def configs_to_customparams(configs, existing):
    if not isinstance(configs, list) or len(configs) != 16:
        raise ValueError("Expected 16 endpoint configurations")
    if not isinstance(existing, dict):
        raise ValueError("Existing parameters must be a dictionary")

    params = dict(existing)

    for num, entry in enumerate(configs, 1):
        if not isinstance(entry, dict):
            raise ValueError(f"Invalid endpoint {num}")

        prefix = f"url{num}_"

        if not str(entry.get("url", "")).strip():
            for key in list(params):
                if key.startswith(prefix):
                    params.pop(key)
            continue

        for key in ("name", "url", "method", "interval", "headers", "body"):
            value = entry.get(key, "")
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            params[prefix + key] = str(value)

        fields = entry.get("fields", {})
        if not isinstance(fields, dict):
            raise ValueError(f"Invalid fields for endpoint {num}")

        for i in range(1, 9):
            field = fields.get(str(i), fields.get(i, {}))
            if not isinstance(field, dict):
                raise ValueError(f"Invalid field {i} for endpoint {num}")

            params[prefix + f"field{i}"] = str(field.get("path", ""))

            for key in ("controller", "on", "off",
                        "on_operator", "off_operator"):
                value = field.get(key, "")
                if key == "controller":
                    value = "true" if str(value).lower() in (
                        "true", "yes", "1", "on"
                    ) else "false"
                params[prefix + f"field{i}_{key}"] = str(value)

    return params



_migration_lock = __import__("threading").Lock()

def migrate_saved_config():
    with _migration_lock:
        return migrate_saved_config_unlocked()

def migrate_saved_config_unlocked():
    source = AUTH_BASE / "data/endpoints.json"
    if not source.exists():
        return False

    backup = source.with_name("endpoints.json.migrated")
    if backup.exists():
        raise RuntimeError("Migration backup already exists; refusing to overwrite")

    configs = json.loads(source.read_text())
    if not isinstance(configs, list) or len(configs) != 16:
        raise ValueError("Invalid saved endpoint configuration")

    if not all(isinstance(entry, dict) for entry in configs):
        raise ValueError("Invalid endpoint entry in saved configuration")

    active = [
        i for i, entry in enumerate(configs, 1)
        if entry.get("url")
    ]

    existing = read_eisy_customparams()
    converted = configs_to_customparams(configs, existing)

    merged = dict(existing)

    for i in active:
        prefix = f"url{i}_"

        # Never overwrite an endpoint already configured in PG3x.
        if str(existing.get(f"{prefix}url", "")).strip():
            continue

        merged.update({
            k: v for k, v in converted.items()
            if k.startswith(prefix)
        })

    if merged != existing:
        write_eisy_customparams(merged)

    verified = read_eisy_customparams()
    for key, value in merged.items():
        if verified.get(key) != value:
            raise RuntimeError(
                f"Migration verification failed for parameter {key}"
            )

    source.rename(backup)
    return True


def read_eisy_customparams():
    if _config_sync is None:
        raise RuntimeError("PG3x configuration bridge not initialized")

    return _config_sync.snapshot()


class HttpControlWebHandler(BaseHTTPRequestHandler):
    controller = None

    SESSION_COOKIE = "http_control_session"

    def session_token(self):
        from http.cookies import SimpleCookie

        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            item = cookie.get(self.SESSION_COOKIE)
            return item.value if item else None
        except Exception:
            return None

    def set_session_cookie(self, token):
        self.send_header(
            "Set-Cookie",
            f"{self.SESSION_COOKIE}={token}; "
            "Path=/; Secure; HttpOnly; SameSite=Strict"
        )

    def clear_session_cookie(self):
        self.send_header(
            "Set-Cookie",
            f"{self.SESSION_COOKIE}=; Path=/; "
            "Max-Age=0; Secure; HttpOnly; SameSite=Strict"
        )


    def is_authenticated(self):
        return validate_session(self.session_token())

    def do_GET(self):
        if self.path == "/login":
            if read_credentials(AUTH_BASE) is None:
                self.send_response(303)
                self.send_header("Location", "/auth")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            page = AUTH_BASE / "http_control_login.html"
            if not page.is_file():
                self.send_error(404, "Login page not installed")
                return

            body = page.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/api/auth/status":
            configured = read_credentials(AUTH_BASE) is not None
            body = json.dumps({
                "configured": configured
            }).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/auth":
            page = AUTH_BASE / "http_control_password.html"
            if not page.is_file():
                self.send_error(404, "Password page not installed")
                return

            body = page.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if not self.is_authenticated():
            if self.path == "/editor":
                destination = (
                    "/login"
                    if read_credentials(AUTH_BASE) is not None
                    else "/auth"
                )
                self.send_response(303)
                self.send_header("Location", destination)
            else:
                self.send_response(401)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if self.path == "/api/config":
            try:
                migrated = migrate_saved_config()
                params = read_eisy_customparams()
                if migrated:
                    self.controller.params = dict(params)
            except Exception:
                if logger := getattr(self.server, "logger", None):
                    logger.exception("Unable to load or migrate eisy-ui configuration")
                self.send_error(500, "Configuration unavailable; original JSON retained if migration failed")
                return

            configs = []

            for num in range(1, 17):
                prefix = f"url{num}_"
                entry = {
                    "name": params.get(prefix + "name", ""),
                    "url": params.get(prefix + "url", ""),
                    "method": params.get(prefix + "method", "GET"),
                    "interval": params.get(prefix + "interval", "0"),
                    "headers": params.get(prefix + "headers", "{}"),
                    "body": params.get(prefix + "body", ""),
                    "fields": {},
                }

                for i in range(1, 9):
                    entry["fields"][i] = {
                        "path": params.get(prefix + f"field{i}", ""),
                        "controller": str(
                            params.get(
                                prefix + f"field{i}_controller", "false"
                            )
                        ).lower() in ("true", "yes", "1", "on"),
                        "on_operator": params.get(
                            prefix + f"field{i}_on_operator", "=="
                        ),
                        "on": params.get(prefix + f"field{i}_on", "1"),
                        "off_operator": params.get(
                            prefix + f"field{i}_off_operator", "=="
                        ),
                        "off": params.get(prefix + f"field{i}_off", "0"),
                    }

                configs.append(entry)

            body = json.dumps(configs).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/editor":
            editor = (
                Path(__file__).resolve().parent
                / "http_control_editor.html"
            )
            body = editor.read_bytes()
            self.send_response(200)
            self.send_header(
                "Content-Type", "text/html; charset=utf-8"
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path != "/":
            self.send_error(404)
            return

        controller = self.controller
        params = dict(controller.params) if controller else {}

        rows = []

        for num in range(1, 17):
            prefix = f"url{num}_"
            name = params.get(prefix + "name", "")
            url = params.get(prefix + "url", "")
            method = params.get(prefix + "method", "GET")
            interval = params.get(prefix + "interval", "0")

            if not name and not url:
                continue

            rows.append(
                "<tr>"
                f"<td>{num}</td>"
                f"<td>{html.escape(str(name))}</td>"
                f"<td>{html.escape(str(method))}</td>"
                f"<td>{html.escape(str(url))}</td>"
                f"<td>{html.escape(str(interval))}</td>"
                "</tr>"
            )

        table_rows = "\n".join(rows) or (
            '<tr><td colspan="5">No endpoints configured</td></tr>'
        )

        page = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HTTP Control</title>
<style>
body {
    font-family: Arial, sans-serif;
    background: #f1f5f9;
    color: #1e293b;
    margin: 30px auto;
    max-width: 1100px;
    padding: 0 20px;
}
h1 {
    background: linear-gradient(135deg, #17365d, #245b91);
    color: white;
    padding: 22px;
    border-radius: 10px;
}
table {
    width: 100%;
    border-collapse: collapse;
    background: white;
}
th, td {
    padding: 12px;
    border-bottom: 1px solid #ddd;
    text-align: left;
    overflow-wrap: anywhere;
}
th { background: #e2e8f0; }
</style>
</head>
<body>
<h1>HTTP Control</h1>
<h2>Configured Endpoints</h2>
<table>
<thead>
<tr>
<th>#</th><th>Name</th><th>Method</th>
<th>URL</th><th>Polling (sec)</th>
</tr>
</thead>
<tbody>
""" + table_rows + """
</tbody>
</table>
<p>Read-only configuration preview</p>
</body>
</html>"""

        body = page.encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)



    def handle_auth_post(self):
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            self.send_error(415, "JSON required")
            return

        # Require requests from the same HTTPS origin.
        if not self.valid_request_origin():
            self.send_error(403, "Invalid origin")
            return

        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 8192:
                raise ValueError("Invalid request size")

            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError("Expected JSON object")

            new_password = data.get("new_password")
            confirmation = data.get("confirm_password")

            if not isinstance(new_password, str):
                raise ValueError("Password required")
            if new_password != confirmation:
                raise ValueError("Passwords do not match")

            with AUTH_LOCK:
                if self.path == "/api/auth/setup":
                    # Initial setup is allowed only before credentials exist.
                    if read_credentials(AUTH_BASE) is not None:
                        raise PermissionError("Password already configured")
                    create_initial_password(
                        AUTH_BASE,
                        new_password,
                    )

                elif self.path == "/api/auth/change":
                    change_password(
                        AUTH_BASE,
                        data.get("current_password", ""),
                        new_password,
                    )

                elif self.path == "/api/auth/recover":
                    complete_recovery(
                        AUTH_BASE,
                        data.get("code", ""),
                        new_password,
                    )

                # Any successful password update invalidates all sessions.
                destroy_all_sessions()

            self.send_response(204)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()

        except PermissionError:
            self.send_error(403, "Authentication failed")
        except (ValueError, TypeError, UnicodeError):
            self.send_error(400, "Invalid password request")
        except OSError:
            self.send_error(500, "Password update failed")

    def handle_login(self):
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            self.send_error(415, "JSON required")
            return

        if not self.valid_request_origin():
            self.send_error(403, "Invalid origin")
            return

        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 8192:
                raise ValueError("Invalid request size")

            data = json.loads(self.rfile.read(size))
            password = data.get("password")
            if not isinstance(password, str):
                raise ValueError("Password required")

            with AUTH_LOCK:
                ip = self.client_address[0]

                if not login_allowed(ip):
                    self.send_error(429, "Too many login attempts")
                    return

                credentials = read_credentials(AUTH_BASE)
                if credentials is None or not check_password(password, *credentials):
                    record_login_failure(ip)
                    self.send_error(403, "Invalid credentials")
                    return

                clear_login_failures(ip)
                token = create_session()

            self.send_response(204)
            self.set_session_cookie(token)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()

        except (ValueError, TypeError, UnicodeError, AttributeError):
            self.send_error(400, "Invalid login request")

    def valid_request_origin(self):
        from urllib.parse import urlsplit

        origin = self.headers.get("Origin")
        if not origin:
            return False

        parsed = urlsplit(origin)
        return (
            parsed.scheme == "https"
            and parsed.netloc == self.headers.get("Host", "")
        )

    def do_POST(self):
        if self.path == "/api/auth/login":
            self.handle_login()
            return

        if self.path == "/api/auth/logout":
            if not self.valid_request_origin():
                self.send_error(403, "Invalid origin")
                return
            destroy_session(self.session_token())
            self.send_response(204)
            self.clear_session_cookie()
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if self.path in (
            "/api/auth/setup",
            "/api/auth/change",
            "/api/auth/recover",
        ):
            self.handle_auth_post()
            return

        if self.path != "/api/config":
            self.send_error(404)
            return

        if not self.valid_request_origin():
            self.send_error(403, "Invalid origin")
            return

        if not self.is_authenticated():
            self.send_response(401)
            self.end_headers()
            return

        # Complete migration before processing the submitted configuration.
        try:
            migrate_saved_config()
        except Exception:
            if logger := getattr(self.server, "logger", None):
                logger.exception("Legacy configuration migration failed")
            self.send_error(500, "Legacy configuration migration failed")
            return

        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 262144:
                raise ValueError("Invalid request size")

            configs = json.loads(self.rfile.read(size))
            if not isinstance(configs, list) or len(configs) != 16:
                raise ValueError("Expected 16 endpoints")

            for entry in configs:
                if not isinstance(entry, dict):
                    raise ValueError("Invalid endpoint")

                method = entry.get("method", "GET")
                if method not in ("GET", "POST", "PUT", "DELETE"):
                    raise ValueError("Invalid HTTP method")

                url = entry.get("url", "")
                if not isinstance(url, str) or (
                    url and not url.startswith(("http://", "https://"))
                ):
                    raise ValueError("URL must begin with http:// or https://")

                interval = int(entry.get("interval", 0))
                if not 0 <= interval <= 86400:
                    raise ValueError("Polling interval must be 0-86400")

                headers = entry.get("headers", "{}") or "{}"
                if isinstance(headers, str):
                    headers = json.loads(headers)
                if not isinstance(headers, dict):
                    raise ValueError("Headers must be a JSON object")

                fields = entry.get("fields", {})
                if not isinstance(fields, dict):
                    raise ValueError("Invalid fields")
                for field in fields.values():
                    if not isinstance(field, dict):
                        raise ValueError("Invalid field")

                    if field.get("controller", False):
                        on_op = field.get("on_operator", "==")
                        off_op = field.get("off_operator", "==")
                        allowed = ("==", "!=", ">", ">=", "<", "<=")

                        if on_op not in allowed or off_op not in allowed:
                            raise ValueError("Invalid scene-controller operator")

                        on = float(field.get("on", 1))
                        off = float(field.get("off", 0))

                        if on_op == off_op == "==" and on == off:
                            raise ValueError("ON and OFF values must differ")

            # Preserve unrelated eisy-ui parameters.
            existing = read_eisy_customparams()
            merged = configs_to_customparams(configs, existing)

            # Save to eisy-ui and verify before applying changes.
            write_eisy_customparams(merged)
            verified = read_eisy_customparams()

            if verified != merged:
                missing = set(merged) - set(verified)
                extra = set(verified) - set(merged)
                changed = {
                    key for key in merged.keys() & verified.keys()
                    if merged[key] != verified[key]
                }
                raise RuntimeError(
                    "Configuration verification failed: "
                    f"{len(missing)} missing, {len(extra)} extra, "
                    f"{len(changed)} changed parameters"
                )

            self.controller.params = dict(verified)

            # Apply configuration to existing and newly configured endpoints.
            self.controller.apply_saved_config(configs)

            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        except (ValueError, TypeError, UnicodeError) as error:
            self.send_error(400, str(error))
        except (OSError, RuntimeError):
            if logger := getattr(self.server, "logger", None):
                logger.exception("Unable to save or verify eisy-ui configuration")
            self.send_error(500, "Unable to save or verify eisy-ui configuration")


def start_web_server(controller, logger=None, host="127.0.0.1", port=8766):
    handler = type(
        "BoundHttpControlWebHandler",
        (HttpControlWebHandler,),
        {"controller": controller},
    )

    server = ThreadingHTTPServer((host, port), handler)
    server.logger = logger

    try:
        cert_file, key_file = ensure_certificate(
            Path(__file__).resolve().parent
        )

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(
            certfile=cert_file,
            keyfile=key_file,
        )

        server.socket = context.wrap_socket(
            server.socket,
            server_side=True,
        )
    except Exception:
        server.server_close()
        raise

    thread = threading.Thread(
        target=server.serve_forever,
        name="HttpControlWeb",
        daemon=True,
    )
    thread.start()

    return server
