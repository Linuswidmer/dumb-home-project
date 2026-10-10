"""The Room Planner, mounted at /rooms/. Layouts are stored in one JSON file
in the data directory (outside the repo, so a git pull never touches it)."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAX_BODY = 10 * 1024 * 1024  # 10 MB is far more than any layout needs
# Always serve fresh files so edits to the app show up on reload.
NO_STORE = {"Cache-Control": "no-store"}
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}

DATA_FILE = Path("rooms.json")  # replaced by configure()
write_lock = threading.Lock()


def configure(*, data_file: Path) -> None:
    global DATA_FILE
    DATA_FILE = data_file


def static_route(name: str, content_type: str):
    def route(req) -> None:
        req.send_file(ROOT / name, content_type, NO_STORE)
    return route


def get_state(req) -> None:
    with write_lock:
        body = DATA_FILE.read_bytes() if DATA_FILE.exists() else b"null"
    req.send_json(200, body, NO_STORE)


def put_state(req) -> None:
    length = int(req.headers.get("Content-Length") or 0)
    if not 0 < length <= MAX_BODY:
        req.send_json(400, {"error": "missing or oversized body"})
        return
    try:
        data = json.loads(req.rfile.read(length))
        if not isinstance(data, dict) or not isinstance(data.get("rooms"), list):
            raise ValueError('expected an object with a "rooms" list')
    except ValueError as err:
        req.send_json(400, {"error": str(err)})
        return

    with write_lock:
        # Write to a temp file first so a crash never leaves a half-written file.
        tmp = DATA_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, DATA_FILE)
    req.send_json(200, {"ok": True})


ROUTES = {
    **{("GET", path): static_route(name, ctype) for path, (name, ctype) in STATIC.items()},
    ("GET", "/api/state"): get_state,
    ("PUT", "/api/state"): put_state,
}
