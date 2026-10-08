#!/usr/bin/env python3
"""A tiny local web app for printing text to the M02 thermal printer.

Serves a minimal HTML form at "/" and a JSON endpoint at POST "/print" so
other people/scripts on your network can send print jobs too. No
authentication — intended for a trusted home/LAN network only.
"""
from __future__ import annotations

import argparse
import io
import json
import random
import ssl
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from PIL import Image, ImageOps, UnidentifiedImageError

from m02_print import ADDR, image_to_rows, print_rows, text_to_image

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


CERT_PATH = Path(__file__).parent / "cert.pem"
KEY_PATH = Path(__file__).parent / "key.pem"

MAX_TEXT_LENGTH = 2000
MAX_IMAGE_BYTES = 15 * 1024 * 1024  # uploads are handled in memory only, never written to disk
MAX_PROMPT_LENGTH = 500
POLLINATIONS_TIMEOUT = 60  # image generation can take a while

PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>M02 Printer</title>
<style>
  body { font-family: sans-serif; max-width: 480px; margin: 2rem auto; padding: 0 1rem; }
  textarea { width: 100%; height: 8rem; font-size: 1rem; box-sizing: border-box; }
  button { margin-top: 0.5rem; padding: 0.5rem 1rem; font-size: 1rem; }
  section { margin-top: 2rem; padding-top: 1rem; border-top: 1px solid #ddd; }
  .status { margin-top: 0.5rem; color: #555; }
  video { width: 100%; margin-top: 0.5rem; display: none; background: #000; }
  .row button { margin-right: 0.5rem; }
</style>
</head>
<body>
<h3>M02 Printer</h3>

<section>
<h4>Text</h4>
<textarea id="text" placeholder="Type something to print..." autofocus></textarea>
<div class="row">
  <button id="send">Print</button>
  <button id="lucky" title="Generate an image from this text with AI and print it">I'm Feeling Lucky!</button>
</div>
<div class="status" id="status">Ctrl+Enter also sends</div>
</section>

<section>
<h4>Image</h4>
<div><input type="file" id="imgfile" accept="image/*"></div>
<div><button id="imgsend">Print Image</button></div>
<div class="status" id="imgstatus"></div>
</section>

<section>
<h4>Webcam</h4>
<video id="video" autoplay playsinline></video>
<div class="row">
  <button id="camstart">Start Camera</button>
  <button id="camcapture">Capture &amp; Print</button>
  <button id="camstop">Stop Camera</button>
</div>
<div class="status" id="camstatus">
  Needs https:// or localhost — browsers block camera access on plain http over the network.
</div>
</section>

<script>
const textEl = document.getElementById('text');
const statusEl = document.getElementById('status');

async function sendText() {
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

document.getElementById('send').addEventListener('click', sendText);
textEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    sendText();
  }
});

async function sendLucky() {
  const text = textEl.value;
  if (!text.trim()) return;
  statusEl.textContent = 'Generating image... (can take up to a minute)';
  try {
    const res = await fetch('/lucky', {
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

document.getElementById('lucky').addEventListener('click', sendLucky);

async function sendImageBlob(blob, statusEl) {
  statusEl.textContent = 'Printing...';
  try {
    const res = await fetch('/print-image', {
      method: 'POST',
      headers: {'Content-Type': blob.type || 'application/octet-stream'},
      body: blob,
    });
    const data = await res.json();
    statusEl.textContent = res.ok ? 'Printed.' : ('Failed: ' + (data.error || res.status));
  } catch (e) {
    statusEl.textContent = 'Failed: ' + e;
  }
}

const imgFile = document.getElementById('imgfile');
const imgStatus = document.getElementById('imgstatus');
document.getElementById('imgsend').addEventListener('click', () => {
  const f = imgFile.files[0];
  if (!f) { imgStatus.textContent = 'Pick a file first.'; return; }
  sendImageBlob(f, imgStatus);
});

let camStream = null;
const video = document.getElementById('video');
const camStatus = document.getElementById('camstatus');
const camStatusDefault = camStatus.textContent;

document.getElementById('camstart').addEventListener('click', async () => {
  try {
    camStream = await navigator.mediaDevices.getUserMedia({video: {facingMode: 'environment'}});
    video.srcObject = camStream;
    video.style.display = 'block';
    camStatus.textContent = 'Camera on.';
  } catch (e) {
    camStatus.textContent = 'Camera failed: ' + e.message + ' (' + camStatusDefault + ')';
  }
});

document.getElementById('camcapture').addEventListener('click', () => {
  if (!camStream) { camStatus.textContent = 'Start the camera first.'; return; }
  const canvas = document.createElement('canvas');
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  canvas.getContext('2d').drawImage(video, 0, 0);
  canvas.toBlob((blob) => sendImageBlob(blob, camStatus), 'image/jpeg', 0.9);
});

document.getElementById('camstop').addEventListener('click', () => {
  if (camStream) {
    camStream.getTracks().forEach((t) => t.stop());
    camStream = null;
  }
  video.style.display = 'none';
  camStatus.textContent = camStatusDefault;
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


def generate_image(prompt: str) -> bytes:
    """Fetch a generated image from Pollinations.ai (no API key required)."""
    encoded = urllib.parse.quote(prompt, safe="")
    seed = random.randint(0, 2**31 - 1)  # avoid getting a cached image for a repeated prompt
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=512&height=512&seed={seed}&nologo=true"
    req = urllib.request.Request(url, headers={"User-Agent": "m02-thermal-printer"})
    with urllib.request.urlopen(req, timeout=POLLINATIONS_TIMEOUT) as resp:
        return resp.read()


def do_print_image(data: bytes) -> None:
    """Decode, print, and discard — the image bytes never touch disk."""
    img = Image.open(io.BytesIO(data))
    img.load()  # force decode now, while the BytesIO backing it is still alive
    img = ImageOps.exif_transpose(img)  # phone/webcam photos often carry rotation metadata
    rows = image_to_rows(img, dither=True)
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
        if self.path == "/print":
            self._handle_print_text()
        elif self.path == "/print-image":
            self._handle_print_image()
        elif self.path == "/lucky":
            self._handle_lucky()
        else:
            self._send_json(404, {"error": "not found"})

    def _handle_print_text(self) -> None:
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

    def _handle_print_image(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            self._send_json(400, {"error": "missing image body"})
            return
        if length > MAX_IMAGE_BYTES:
            self._send_json(400, {"error": f"image too large (max {MAX_IMAGE_BYTES // (1024 * 1024)}MB)"})
            return

        raw = self.rfile.read(length)

        try:
            do_print_image(raw)
        except UnidentifiedImageError:
            self._send_json(400, {"error": "not a recognizable image"})
            return
        except Exception as exc:  # noqa: BLE001 - report any failure to the client
            self._send_json(502, {"error": str(exc)})
            return
        finally:
            del raw  # drop the reference promptly; nothing here ever touches disk

        self._send_json(200, {"ok": True})

    def _handle_lucky(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        try:
            text = json.loads(raw.decode("utf-8")).get("text")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, {"error": "invalid JSON body"})
            return

        if not text or not text.strip():
            self._send_json(400, {"error": "missing 'text'"})
            return
        if len(text) > MAX_PROMPT_LENGTH:
            self._send_json(400, {"error": f"prompt too long (max {MAX_PROMPT_LENGTH} chars)"})
            return

        try:
            image_bytes = generate_image(text)
        except urllib.error.HTTPError as exc:
            self._send_json(502, {"error": f"image generation failed: HTTP {exc.code}"})
            return
        except (urllib.error.URLError, TimeoutError) as exc:
            self._send_json(502, {"error": f"image generation failed: {exc}"})
            return

        try:
            do_print_image(image_bytes)
        except UnidentifiedImageError:
            self._send_json(502, {"error": "image generation returned something unprintable"})
            return
        except Exception as exc:  # noqa: BLE001 - report any failure to the client
            self._send_json(502, {"error": str(exc)})
            return
        finally:
            del image_bytes  # drop the reference promptly; nothing here ever touches disk

        self._send_json(200, {"ok": True})


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
                "-subj", "/CN=m02-printer",
            ],
            check=True,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        detail = exc.stderr.decode() if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        print(f"Failed to generate a self-signed cert (is openssl installed?): {detail}", file=sys.stderr)
        raise SystemExit(1)
    key_path.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser(description="Local web app for the M02 thermal printer")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0, reachable on your LAN)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--addr", default=ADDR, help="Printer Bluetooth MAC address")
    parser.add_argument("--font-size", type=int, default=32)
    parser.add_argument("--density", type=int, default=4, choices=(1, 2, 3, 4))
    parser.add_argument("--http", action="store_true", help="Serve plain HTTP instead of self-signed HTTPS (disables webcam capture from other devices)")
    args = parser.parse_args()

    Config.addr = args.addr
    Config.font_size = args.font_size
    Config.density = args.density

    scheme = "http"
    if args.http:
        server = ThreadingHTTPServer((args.host, args.port), Handler)
    else:
        ensure_self_signed_cert(CERT_PATH, KEY_PATH)
        server = ThreadingHTTPSServer((args.host, args.port), Handler, certfile=str(CERT_PATH), keyfile=str(KEY_PATH))
        scheme = "https"

    print(f"Serving on {scheme}://{args.host}:{args.port}")
    if scheme == "https":
        print("  (self-signed cert — your browser will warn once, click through to continue)")
    print('  POST /print        JSON {"text": "..."}')
    print("  POST /print-image  raw image bytes (Content-Type: image/*)")
    print('  POST /lucky        JSON {"text": "..."} — AI-generates an image from the text via Pollinations.ai and prints it')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
