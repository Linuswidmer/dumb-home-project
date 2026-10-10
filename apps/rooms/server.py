#!/usr/bin/env python3
"""Serve the Room Planner locally and store its data in data.json next to this file."""

import argparse
import json
import os
import threading
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data.json"
API_PATH = "/api/state"
MAX_BODY = 10 * 1024 * 1024  # 10 MB is far more than any layout needs

write_lock = threading.Lock()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        # Always serve fresh files so edits to the app show up on reload.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path.split("?")[0] == API_PATH:
            with write_lock:
                body = DATA_FILE.read_bytes() if DATA_FILE.exists() else b"null"
            self.send_json(HTTPStatus.OK, body)
        else:
            super().do_GET()

    def do_PUT(self):
        if self.path.split("?")[0] != API_PATH:
            self.send_json(HTTPStatus.NOT_FOUND, b'{"error": "not found"}')
            return
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= MAX_BODY:
            self.send_json(HTTPStatus.BAD_REQUEST, b'{"error": "missing or oversized body"}')
            return
        try:
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict) or not isinstance(data.get("rooms"), list):
                raise ValueError('expected an object with a "rooms" list')
        except ValueError as err:
            self.send_json(HTTPStatus.BAD_REQUEST, json.dumps({"error": str(err)}).encode())
            return

        with write_lock:
            # Write to a temp file first so a crash never leaves a half-written data.json.
            tmp = DATA_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(tmp, DATA_FILE)
        self.send_json(HTTPStatus.OK, b'{"ok": true}')

    def send_json(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        # Autosave would otherwise flood the terminal.
        if API_PATH not in self.path:
            super().log_message(fmt, *args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true", help="don't open the app in a browser")
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Room Planner running at {url}")
    print(f"Saving to {DATA_FILE}")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
