#!/usr/bin/env python3
"""A tiny local web app for printing text to the M02 thermal printer.

Serves a minimal HTML form at "/" and a JSON endpoint at POST "/print" so
other people/scripts on your network can send print jobs too. No
authentication — intended for a trusted home/LAN network only.
"""
from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from m02_print import ADDR, image_to_rows, print_rows, text_to_image

MAX_TEXT_LENGTH = 2000

PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>M02 Printer</title>
<style>
  body { font-family: sans-serif; max-width: 480px; margin: 2rem auto; padding: 0 1rem; }
  textarea { width: 100%; height: 8rem; font-size: 1rem; box-sizing: border-box; }
  button { margin-top: 0.5rem; padding: 0.5rem 1rem; font-size: 1rem; }
  #status { margin-top: 0.5rem; color: #555; }
</style>
</head>
<body>
<h3>M02 Printer</h3>
<textarea id="text" placeholder="Type something to print..." autofocus></textarea>
<div><button id="send">Print</button></div>
<div id="status">Ctrl+Enter also sends</div>
<script>
const textEl = document.getElementById('text');
const statusEl = document.getElementById('status');

async function send() {
  const text = textEl.value;
  if (!text.trim()) return;
  statusEl.textContent = 'Printing...';
  try {
    const res = await fetch('/print', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text}),
    });
    const data = await res.json();
    if (res.ok) {
      statusEl.textContent = 'Printed.';
      textEl.value = '';
    } else {
      statusEl.textContent = 'Failed: ' + (data.error || res.status);
    }
  } catch (e) {
    statusEl.textContent = 'Failed: ' + e;
  }
}

document.getElementById('send').addEventListener('click', send);
textEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    send();
  }
});
</script>
</body>
</html>
"""

_print_lock = threading.Lock()


class Config:
    addr: str = ADDR
    font_size: int = 32
    density: int = 4


def do_print(text: str) -> None:
    img = text_to_image(text, font_size=Config.font_size)
    rows = image_to_rows(img, dither=False)
    with _print_lock:
        print_rows(rows, addr=Config.addr, density_level=Config.density)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/print":
            self._send_json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        content_type = self.headers.get("Content-Type", "")

        text = None
        if "application/json" in content_type:
            try:
                text = json.loads(raw.decode("utf-8")).get("text")
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send_json(400, {"error": "invalid JSON body"})
                return
        else:
            form = parse_qs(raw.decode("utf-8", errors="replace"))
            text = form.get("text", [None])[0]

        if not text or not text.strip():
            self._send_json(400, {"error": "missing 'text'"})
            return
        if len(text) > MAX_TEXT_LENGTH:
            self._send_json(400, {"error": f"text too long (max {MAX_TEXT_LENGTH} chars)"})
            return

        try:
            do_print(text)
        except Exception as exc:  # noqa: BLE001 - report any failure to the client
            self._send_json(502, {"error": str(exc)})
            return

        self._send_json(200, {"ok": True})


def main() -> None:
    parser = argparse.ArgumentParser(description="Local web app for the M02 thermal printer")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0, reachable on your LAN)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--addr", default=ADDR, help="Printer Bluetooth MAC address")
    parser.add_argument("--font-size", type=int, default=32)
    parser.add_argument("--density", type=int, default=4, choices=(1, 2, 3, 4))
    args = parser.parse_args()

    Config.addr = args.addr
    Config.font_size = args.font_size
    Config.density = args.density

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Serving on http://{args.host}:{args.port}  (POST /print with JSON {{\"text\": \"...\"}})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
