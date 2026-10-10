"""The Room Planner, mounted at /rooms/. Layouts are stored in one JSON file
in the data directory (outside the repo, so a git pull never touches it).

Each room is saved on its own (PUT/DELETE api/rooms?id=...), so people working
on different rooms at the same time don't overwrite each other. There is
deliberately no way to replace the whole file: a tab still running an old
version of the page that does that gets an error instead of wiping others' rooms.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

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


def _room_id(req) -> str | None:
    ids = parse_qs(urlsplit(req.path).query).get("id")
    return ids[0] if ids and ids[0] else None


def _update_rooms(change) -> None:
    """Apply `change` to the stored rooms list under the lock and write it back."""
    with write_lock:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8")) if DATA_FILE.exists() else None
        if not isinstance(data, dict) or not isinstance(data.get("rooms"), list):
            data = {"rooms": []}
        data["rooms"] = change(data["rooms"])
        # Write to a temp file first so a crash never leaves a half-written file.
        tmp = DATA_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, DATA_FILE)


def put_room(req) -> None:
    room_id = _room_id(req)
    length = int(req.headers.get("Content-Length") or 0)
    if room_id is None or not 0 < length <= MAX_BODY:
        req.send_json(400, {"error": "missing room id, or missing or oversized body"})
        return
    try:
        room = json.loads(req.rfile.read(length))
        if not isinstance(room, dict) or room.get("id") != room_id:
            raise ValueError("expected a room object whose id matches ?id=")
    except ValueError as err:
        req.send_json(400, {"error": str(err)})
        return

    def upsert(rooms):
        for i, r in enumerate(rooms):
            if isinstance(r, dict) and r.get("id") == room_id:
                rooms[i] = room
                return rooms
        return rooms + [room]

    _update_rooms(upsert)
    req.send_json(200, {"ok": True})


def delete_room(req) -> None:
    room_id = _room_id(req)
    if room_id is None:
        req.send_json(400, {"error": "missing room id"})
        return
    _update_rooms(lambda rooms: [r for r in rooms if not (isinstance(r, dict) and r.get("id") == room_id)])
    req.send_json(200, {"ok": True})


ROUTES = {
    **{("GET", path): static_route(name, ctype) for path, (name, ctype) in STATIC.items()},
    ("GET", "/api/state"): get_state,
    ("PUT", "/api/rooms"): put_room,
    ("DELETE", "/api/rooms"): delete_room,
}
