#!/usr/bin/env python3
"""dumb-home-project: one small server for the home's web apps.

  https://<pi>:8765/           landing page
  https://<pi>:8765/printer/   M02 thermal printer
  https://<pi>:8765/rooms/     room planner
  https://<pi>:8765/transit/   BVG departures
  http://<pi>:5001/            BVG departures for the e-reader (its app has
                               this URL baked in — keep it plain HTTP)

Everything runs in this one process with only the standard library and Pillow.
No authentication — intended for a trusted home network only.
"""
from __future__ import annotations

import argparse
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from apps.printer import routes as printer
from apps.printer.m02_print import ADDR
from apps.rooms import routes as rooms
from apps.transit import departures as transit
from web import ThreadingHTTPSServer, ensure_self_signed_cert, make_handler

APPS = {
    # prefix: (title, description, routes)
    "/printer": ("Printer", "Print text, images and webcam shots on the thermal printer", printer.ROUTES),
    "/rooms": ("Room planner", "Lay out furniture in a room", rooms.ROUTES),
    "/transit": ("Departures", "Next trains and buses from Erkstraße and Rathaus Neukölln", transit.ROUTES),
}
DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / "dumb-home-project"


def landing_page(req) -> None:
    items = "\n".join(
        f'<li><a href="{prefix}/">{title}</a><span>{description}</span></li>'
        for prefix, (title, description, _) in APPS.items()
    )
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>dumb-home-project</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 32rem; margin: 3rem auto; padding: 0 1rem;
         background: #fafafa; color: #222; }}
  ul {{ list-style: none; padding: 0; }}
  li {{ margin: 0 0 1rem; }}
  a {{ font-size: 1.25rem; color: inherit; }}
  span {{ display: block; color: #666; }}
  @media (prefers-color-scheme: dark) {{ body {{ background: #1a1a1a; color: #eee; }} span {{ color: #aaa; }} }}
</style>
</head>
<body>
<h1>dumb-home-project</h1>
<ul>
{items}
</ul>
</body>
</html>
"""
    req.send_body(200, html.encode("utf-8"), "text/html; charset=utf-8")


def build_routes() -> dict:
    routes = {("GET", "/"): landing_page}
    for prefix, (_, _, app_routes) in APPS.items():
        # Pages use relative URLs, so they must be loaded with the trailing slash.
        routes[("GET", prefix)] = lambda req, prefix=prefix: req.redirect(prefix + "/")
        for (method, path), route in app_routes.items():
            routes[(method, prefix + path)] = route
    return routes


def main() -> None:
    parser = argparse.ArgumentParser(description="dumb-home-project: the printer, room planner and departures apps")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0, reachable on your LAN)")
    parser.add_argument("--port", type=int, default=8765, help="Port for all apps (default: 8765)")
    parser.add_argument("--transit-port", type=int, default=5001,
                        help="Plain-HTTP port for the e-reader's departures page (default: 5001, 0 to disable)")
    parser.add_argument("--http", action="store_true",
                        help="Serve plain HTTP on --port instead of self-signed HTTPS (disables webcam capture from other devices)")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR,
                        help=f"Where room layouts and the TLS cert live (default: {DEFAULT_DATA_DIR})")
    parser.add_argument("--addr", default=ADDR, help="Printer Bluetooth MAC address")
    parser.add_argument("--font-size", type=int, default=32)
    parser.add_argument("--density", type=int, default=4, choices=(1, 2, 3, 4))
    args = parser.parse_args()

    args.data_dir.mkdir(parents=True, exist_ok=True)
    printer.configure(addr=args.addr, font_size=args.font_size, density=args.density)
    rooms.configure(data_file=args.data_dir / "rooms.json")

    handler = make_handler(build_routes())
    if args.http:
        server = ThreadingHTTPServer((args.host, args.port), handler)
        scheme = "http"
    else:
        cert, key = args.data_dir / "cert.pem", args.data_dir / "key.pem"
        ensure_self_signed_cert(cert, key)
        server = ThreadingHTTPSServer((args.host, args.port), handler, certfile=str(cert), keyfile=str(key))
        scheme = "https"
    print(f"Serving on {scheme}://{args.host}:{args.port}/  (apps: {', '.join(p + '/' for p in APPS)})")
    if scheme == "https":
        print("  (self-signed cert — your browser will warn once, click through to continue)")
    print(f"Room layouts are saved to {args.data_dir / 'rooms.json'}")

    if args.transit_port:
        transit_server = ThreadingHTTPServer((args.host, args.transit_port), make_handler(transit.ROUTES))
        threading.Thread(target=transit_server.serve_forever, daemon=True).start()
        print(f"Departures for the e-reader on http://{args.host}:{args.transit_port}/")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
