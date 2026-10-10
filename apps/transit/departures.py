"""BVG departure monitor (Erkstraße / U Rathaus Neukölln), shown on the e-reader.

The e-reader's app has http://<pi>:5001/ baked in, so server.py serves these
routes there unchanged, in addition to /transit/ on the main server.

Departures are fetched lazily: only when someone asks and the cached copy is
older than CACHE_SECONDS, so nothing hits the BVG API while nobody's looking.
The countdown is computed per request from the absolute departure times.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

STOPS = {
    "Erkstraße": "900075101",
    "U Rathaus Neukölln": "900078102",
}
TIMEWINDOW_MIN = 15
CACHE_SECONDS = 10
PER_LINE_AND_DIRECTION = 3
BERLIN = ZoneInfo("Europe/Berlin")
PAGE_FILE = Path(__file__).parent / "departures.html"
# The page polls every 10s; flask_cors allowed any origin, so keep doing that.
CORS = {"Access-Control-Allow-Origin": "*"}

# Per stop: the last successfully fetched departures, kept if a later fetch
# fails — their absolute times stay valid and keep counting down correctly.
_departures: dict[str, list[dict]] = {name: [] for name in STOPS}
_fetched_at = 0.0
_lock = threading.Lock()


def fetch_with_retry(url, retries=3, retry_sleep_time=2):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "dumb-home-project"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.load(resp)
        except Exception:
            if attempt < retries - 1:
                time.sleep(retry_sleep_time)
            else:
                raise


def get_next_departures(stop_id: str) -> list[dict]:
    response_json = fetch_with_retry(
        f"https://v6.bvg.transport.rest/stops/{stop_id}/departures?duration={TIMEWINDOW_MIN}"
    )
    rows = []
    for d in response_json.get("departures", []):
        try:
            if not d.get("when") or not d.get("plannedWhen"):
                print("'when' or 'plannedWhen' empty in API call - departure gets ignored")
                continue
            if stop_id == "900078102" and d["line"]["name"] != "U7":
                continue
            when = datetime.fromisoformat(d["when"])
            rows.append({
                "line": d["line"]["name"],
                "direction": d["direction"],
                "when": when if when.tzinfo else when.replace(tzinfo=BERLIN),
            })
        except Exception as e:
            print(f"Skipping departure due to unexpected data: {e} | raw: {d}")
    return rows


def _refresh() -> None:
    global _fetched_at
    for stop_name, stop_id in STOPS.items():
        try:
            _departures[stop_name] = get_next_departures(stop_id)
        except Exception as e:
            print(f"Failed to fetch API data for stop id: {stop_id}: {e}")
    _fetched_at = time.monotonic()


def current_departures() -> dict:
    with _lock:
        if time.monotonic() - _fetched_at >= CACHE_SECONDS:
            _refresh()
        upcoming = [dict(d, stop=stop) for stop, deps in _departures.items() for d in deps]

    now = datetime.now(BERLIN)
    shown = Counter()
    result = []
    for d in sorted(upcoming, key=lambda d: d["when"]):
        time_left = int((d["when"] - now).total_seconds())
        key = (d["line"], d["direction"])
        if time_left < 0 or shown[key] >= PER_LINE_AND_DIRECTION:
            continue
        shown[key] += 1
        minutes, seconds = divmod(time_left, 60)
        result.append({
            "line": d["line"],
            "direction": d["direction"],
            "minutes": minutes,
            "seconds": seconds,
            "leaves_in": f"{minutes:02d}:{seconds:02d}",
            "stop": d["stop"],
        })

    return {
        "departures": result,
        "time": now.strftime("%H:%M:%S"),
        "date": now.strftime("%d.%m.%Y"),
    }


def page(req) -> None:
    req.send_file(PAGE_FILE, "text/html; charset=utf-8", CORS)


def api_departures(req) -> None:
    # Always 200: the e-reader page only schedules its next refresh after a
    # successful response, so an error here would freeze the display.
    try:
        payload = current_departures()
    except Exception as e:
        print(f"Building departures failed: {e}")
        now = datetime.now(BERLIN)
        payload = {"departures": [], "time": now.strftime("%H:%M:%S"), "date": now.strftime("%d.%m.%Y")}
    req.send_json(200, payload, CORS)


ROUTES = {
    ("GET", "/"): page,
    ("GET", "/api/departures"): api_departures,
}
