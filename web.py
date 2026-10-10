"""The HTTP plumbing every app shares: a request handler that dispatches to a
flat route table, a few response helpers, and the self-signed TLS server.

Each app exposes ROUTES, a dict of {(method, path): handler_function}, where
the function takes the request handler (`req`) and writes the response with
the helpers below. server.py mounts each app's routes under its own prefix.
"""
from __future__ import annotations

import json
import ssl
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

Route = Callable[["Handler"], None]


class Handler(BaseHTTPRequestHandler):
    """Dispatches requests to `routes`; make_handler() builds one per server.

    An exception in a route only fails that one request — socketserver logs
    the traceback and keeps serving everything else.
    """

    routes: dict[tuple[str, str], Route] = {}

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_PUT(self) -> None:
        self._dispatch("PUT")

    def _dispatch(self, method: str) -> None:
        path = urlsplit(self.path).path
        route = self.routes.get((method, path))
        if route is not None:
            route(self)
        elif any(p == path for _, p in self.routes):
            self.send_json(405, {"error": "method not allowed"})
        else:
            self.send_json(404, {"error": "not found"})

    # --- response helpers -------------------------------------------------

    def send_body(self, status: int, body: bytes, content_type: str, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status: int, payload: dict | bytes, headers: dict[str, str] | None = None) -> None:
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.send_body(status, body, "application/json", headers)

    def send_file(self, path: Path, content_type: str, headers: dict[str, str] | None = None) -> None:
        self.send_body(200, path.read_bytes(), content_type, headers)

    def redirect(self, location: str) -> None:
        self.send_response(301)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length > 0 else b""

    # --- logging ----------------------------------------------------------

    def log_request(self, code="-", size="-") -> None:
        # Status checks, departure refreshes and autosaves arrive every few
        # seconds; logging all of them would just churn the Pi's SD card.
        # Keep errors and print jobs.
        if str(code).isdigit() and (int(code) >= 400 or self.command == "POST"):
            super().log_request(code, size)

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}")


def make_handler(routes: dict[tuple[str, str], Route]) -> type[Handler]:
    return type("RoutedHandler", (Handler,), {"routes": routes})


class ThreadingHTTPSServer(ThreadingHTTPServer):
    """ThreadingHTTPServer that TLS-wraps each connection in its own worker
    thread, not the shared listening socket.

    Wrapping the listening socket directly (the usual one-liner recipe)
    makes socketserver's single-threaded accept loop perform the TLS
    handshake synchronously for every connection — so one slow or stuck
    client (e.g. a browser retrying a cert prompt) blocks every other
    client, including unrelated requests, until that handshake times out.
    """

    def __init__(self, addr, handler, certfile: str, keyfile: str):
        super().__init__(addr, handler)
        self.ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ssl_context.load_cert_chain(certfile=certfile, keyfile=keyfile)

    def process_request(self, request, client_address):
        thread = threading.Thread(
            target=self._handshake_and_process, args=(request, client_address), daemon=self.daemon_threads
        )
        thread.start()

    def _handshake_and_process(self, request, client_address) -> None:
        try:
            tls_request = self.ssl_context.wrap_socket(request, server_side=True)
        except (ssl.SSLError, OSError):
            request.close()
            return
        try:
            self.finish_request(tls_request, client_address)
        except Exception:
            self.handle_error(tls_request, client_address)
        finally:
            self.shutdown_request(tls_request)


def ensure_self_signed_cert(cert_path: Path, key_path: Path) -> None:
    """Generate a self-signed cert/key pair if one doesn't already exist.

    Browsers only allow camera access (getUserMedia) on a secure context —
    https, or http on localhost. A self-signed cert is enough to satisfy
    that: the browser just needs the scheme to be https, not a CA-trusted
    certificate. Each host generates (and keeps) its own cert/key; neither
    is ever committed to the repo.
    """
    if cert_path.exists() and key_path.exists():
        return
    print(f"No TLS cert found, generating a self-signed one at {cert_path} ...")
    try:
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048",
                "-keyout", str(key_path), "-out", str(cert_path),
                "-days", "3650", "-nodes",
                "-subj", "/CN=dumb-home-project",
            ],
            check=True,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        detail = exc.stderr.decode() if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        print(f"Failed to generate a self-signed cert (is openssl installed?): {detail}", file=sys.stderr)
        raise SystemExit(1)
    key_path.chmod(0o600)
