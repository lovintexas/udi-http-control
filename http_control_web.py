#!/usr/bin/env python3
import ssl
from http_control_tls import ensure_certificate
from http_control_auth import (
    check_authorization,
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


class HttpControlWebHandler(BaseHTTPRequestHandler):
    controller = None

    def is_authenticated(self):
        with AUTH_LOCK:
            credentials = read_credentials(AUTH_BASE)
            if credentials is None:
                return False
            return check_authorization(
                self.headers.get("Authorization"),
                *credentials,
            )

    def do_GET(self):
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
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="HTTP Control"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if self.path == "/api/config":
            saved_file = Path(__file__).resolve().parent / "data" / "endpoints.json"
            if saved_file.is_file():
                try:
                    with saved_file.open() as source:
                        saved = json.load(source)
                    if isinstance(saved, list) and len(saved) == 16:
                        body = json.dumps(saved).encode("utf-8")
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                        return
                except (OSError, ValueError) as error:
                    if logger := getattr(self.server, "logger", None):
                        logger.warning("Could not load saved configuration: %s", error)

            params = dict(self.controller.params)
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

        # Reject cross-origin browser requests.
        origin = self.headers.get("Origin")
        if origin:
            from urllib.parse import urlsplit
            parsed = urlsplit(origin)
            host = self.headers.get("Host", "")
            if parsed.scheme != "https" or parsed.netloc != host:
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

    def do_POST(self):
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

        if not self.is_authenticated():
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="HTTP Control"')
            self.end_headers()
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

            directory = Path(__file__).resolve().parent / "data"
            directory.mkdir(parents=True, exist_ok=True)

            fd, temporary = tempfile.mkstemp(dir=directory)
            try:
                with os.fdopen(fd, "w") as output:
                    json.dump(configs, output, indent=2)
                    output.flush()
                    os.fsync(output.fileno())
                os.chmod(temporary, 0o600)
                os.replace(temporary, directory / "endpoints.json")
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

            # Apply configuration to existing and newly configured endpoints.
            self.controller.apply_saved_config(configs)

            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        except (ValueError, TypeError, UnicodeError) as error:
            self.send_error(400, str(error))
        except OSError:
            self.send_error(500, "Unable to save configuration")


def start_web_server(controller, logger=None, host="127.0.0.1", port=8766):
    handler = type(
        "BoundHttpControlWebHandler",
        (HttpControlWebHandler,),
        {"controller": controller},
    )

    server = ThreadingHTTPServer((host, port), handler)

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
