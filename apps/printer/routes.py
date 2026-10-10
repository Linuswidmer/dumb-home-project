"""The M02 thermal printer web app, mounted at /printer/.

Serves the "playground" page and JSON endpoints so anyone on the LAN can send
print jobs. No authentication — intended for a trusted home network only.
"""
from __future__ import annotations

import io
import json
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import parse_qs

from PIL import Image, ImageOps, UnidentifiedImageError

from .m02_print import ADDR, RFCOMM_CHANNEL, image_to_rows, print_rows, text_to_image, wrap_text

MAX_TEXT_LENGTH = 2000
MAX_IMAGE_BYTES = 15 * 1024 * 1024  # uploads are handled in memory only, never written to disk
MAX_PROMPT_LENGTH = 500
POLLINATIONS_TIMEOUT = 60  # image generation can take a while

PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>M02 Printer</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Special+Elite&display=swap" rel="stylesheet">
<link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">
<style>
  * { box-sizing: border-box; }
  body {
    font-family: arial, sans-serif;
    background: #f1f3f4;
    color: #000;
    margin: 0;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 2rem 1rem;
  }

  .app {
    width: 440px;
    max-width: 92vw;
    height: 80vh;
    max-height: 820px;
    display: flex;
    flex-direction: column;
  }

  .greeting {
    margin-bottom: 1.2rem;
    overflow: hidden; /* contain the floated .hello */
  }
  .greeting .hello {
    float: left;
    font-family: "Courier New", monospace;
    font-size: 1.8rem;
    font-weight: normal;
    color: #202124;
  }
  /* .proverb: cut for now, coming back to it later — font link for
     Special Elite stays loaded in <head> in the meantime. */

  .tabbar {
    display: flex;
    justify-content: flex-end;
    gap: 0.3rem;
  }
  .tab {
    padding: 0.6rem 1.3rem;
    font-size: 0.85rem;
    color: #5f6368;
    background: #e3e5e8;
    border: 1px solid #c9ccd1;
    border-bottom: none;
    border-radius: 8px 8px 0 0;
    cursor: pointer;
    user-select: none;
    position: relative;
  }
  .tab:hover { background: #ebedef; color: #202124; }
  .tab.active {
    background: #fff;
    color: #202124;
    font-weight: bold;
    z-index: 1;
    margin-bottom: -1px;
    padding-bottom: calc(0.6rem + 1px);
  }

  .playground {
    background: #fff;
    border: 1px solid #c9ccd1;
    border-radius: 8px 0 8px 8px;
    padding: 2.5rem 2rem;
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  .panel {
    width: 100%;
    flex: 1;
    min-height: 0;
    text-align: center;
    display: flex;
    flex-direction: column;
    align-items: center;
  }
  .panel[hidden] { display: none; }

  .actions {
    margin-top: auto;
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  textarea {
    width: 320px;
    max-width: 100%;
    flex: 1;
    min-height: 0;
    padding: 0;
    font-size: 1.1rem;
    font-family: arial, sans-serif;
    background: transparent;
    border: none;
    outline: none;
    box-shadow: none;
    resize: none;
    overflow: hidden;
    vertical-align: top;
    caret-color: #4285F4;
  }
  textarea::placeholder { color: #c7c9cc; }

  .row { margin-top: 1.6rem; }
  button, input[type="file"]::file-selector-button, input[type="file"]::-webkit-file-upload-button {
    background-color: #f2f2f2;
    border: 1px solid #f2f2f2;
    border-radius: 4px;
    color: #3c4043;
    font-family: arial, sans-serif;
    font-size: 0.85rem;
    padding: 0.55rem 1rem;
    margin: 0 0.3rem;
    cursor: pointer;
  }
  button:hover,
  input[type="file"]:hover::file-selector-button,
  input[type="file"]:hover::-webkit-file-upload-button {
    border-color: #dadce0;
    box-shadow: 0 1px 1px rgba(0,0,0,0.1);
    color: #202124;
  }

  .icon-btn {
    width: 56px;
    height: 56px;
    padding: 0;
    border-radius: 50%;
  }
  .icon-btn .material-icons { font-size: 26px; line-height: 1; }

  .status {
    margin-top: 1.2rem;
    color: #70757a;
    font-size: 0.8rem;
    min-height: 1.2em;
    text-align: center;
  }

  input[type="file"] { font-size: 0.85rem; color: #5f6368; }

  #imgpreview {
    display: none;
    max-width: 100%;
    max-height: 50vh;
    margin-top: 1.2rem;
    border-radius: 4px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.2);
  }

  video {
    width: 100%;
    max-height: 50vh;
    object-fit: cover;
    margin-top: 0;
    display: none;
    background: #000;
    border-radius: 4px;
    filter: grayscale(1) contrast(1.1);
  }

  .footer {
    margin-top: 1.2rem;
    font-size: 0.78rem;
    color: #9aa0a6;
    text-align: center;
  }
  .footer .sep { margin: 0 0.5rem; }
  .footer .dot {
    display: inline-block;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #c7c9cc;
    margin-right: 0.4rem;
  }
</style>
</head>
<body>

<div class="app">
<div class="greeting">
  <div class="hello" id="hello"></div>
</div>
<div class="tabbar">
  <div class="tab active" id="tab-text">Text</div>
  <div class="tab" id="tab-image">Image</div>
  <div class="tab" id="tab-webcam">Webcam</div>
</div>

<div class="playground">

<div class="panel" id="panel-text">
<textarea id="text" autofocus rows="1"></textarea>
<div class="actions">
<div class="row">
  <button id="send" class="icon-btn" title="Print" aria-label="Print"><span class="material-icons">print</span></button>
  <button id="lucky" class="icon-btn" title="I'm Feeling Lucky! (ask an AI, print the reply)" aria-label="I'm Feeling Lucky!"><span class="material-icons">casino</span></button>
</div>
<div class="status" id="status"></div>
</div>
</div>

<div class="panel" id="panel-image" hidden>
<div><input type="file" id="imgfile" accept="image/*"></div>
<img id="imgpreview" alt="">
<div class="actions">
<div class="row">
  <button id="imgsend" class="icon-btn" title="Print Image" aria-label="Print Image"><span class="material-icons">print</span></button>
</div>
<div class="status" id="imgstatus"></div>
</div>
</div>

<div class="panel" id="panel-webcam" hidden>
<video id="video" autoplay playsinline></video>
<div class="actions">
<div class="row">
  <button id="camtoggle" class="icon-btn" title="Start Camera" aria-label="Start Camera"><span class="material-icons">videocam</span></button>
  <button id="camcapture" class="icon-btn" title="Capture &amp; Print" aria-label="Capture &amp; Print"><span class="material-icons">photo_camera</span></button>
  <button id="camswitch" class="icon-btn" title="Switch Camera" aria-label="Switch Camera"><span class="material-icons">flip_camera_ios</span></button>
</div>
<div class="status" id="camstatus"></div>
</div>
</div>

</div>
</div>

<div class="footer">
  <span class="dot" id="printer-dot"></span><span id="printer-label">Checking printer…</span>
  <span class="sep">·</span>
  Made with 📄 in Berlin
</div>

<script>
// Parked for later — a rotating proverb line under the heading, set in italic
// Special Elite (already loaded in <head>). Re-add a #proverb element and
// call PROVERBS[Math.floor(Math.random() * PROVERBS.length)] to bring it back.
const PROVERBS = [
  "A receipt in hand is worth two in the cloud.",
  "He who prints twice, measures never.",
  "The thermal head forgives, but the paper roll remembers.",
  "Ink is temporary; thermal paper is... also temporary, actually.",
  "Good things come to those who wait ~24 seconds for Pollinations.ai.",
  "Feed the printer before it feeds on your patience.",
];

function greet() {
  document.getElementById('hello').textContent = 'https://drucken:3000';
}
greet();

const printerDot = document.getElementById('printer-dot');
const printerLabel = document.getElementById('printer-label');
async function checkPrinterStatus() {
  try {
    const res = await fetch('printer-status');
    const data = await res.json();
    printerDot.style.background = data.connected ? '#34A853' : '#EA4335';
    printerLabel.textContent = data.connected ? 'Printer online' : 'Printer offline';
  } catch (e) {
    printerDot.style.background = '#EA4335';
    printerLabel.textContent = 'Printer offline';
  }
}
checkPrinterStatus();
setInterval(checkPrinterStatus, 20000);

const tabs = ['text', 'image', 'webcam'];
function showTab(name) {
  for (const t of tabs) {
    document.getElementById('panel-' + t).hidden = (t !== name);
    document.getElementById('tab-' + t).classList.toggle('active', t === name);
  }
}
for (const t of tabs) {
  document.getElementById('tab-' + t).addEventListener('click', () => showTab(t));
}

const textEl = document.getElementById('text');
const statusEl = document.getElementById('status');

// Typewriter placeholder: cycles example prompts into the empty textarea's
// placeholder, one character at a time. Swap this list for whatever you like.
const PLACEHOLDER_EXAMPLES = ["GuMo :)", "Vegetarisches Mittagessen Rezept"];
let placeholderIndex = 0;
function typePlaceholder() {
  const target = PLACEHOLDER_EXAMPLES[placeholderIndex % PLACEHOLDER_EXAMPLES.length];
  let i = 0;
  const step = () => {
    if (textEl.value) { setTimeout(step, 400); return; } // wait out any typed text before continuing
    textEl.placeholder = target.slice(0, i);
    if (i < target.length) {
      i++;
      setTimeout(step, 180);
    } else {
      setTimeout(() => {
        placeholderIndex++;
        typePlaceholder();
      }, 4000);
    }
  };
  step();
}
typePlaceholder();

async function sendText() {
  const text = textEl.value;
  if (!text.trim()) return;
  statusEl.textContent = 'Printing...';
  try {
    const res = await fetch('print', {
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
  statusEl.textContent = 'Asking the AI...';
  try {
    const res = await fetch('lucky', {
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
    const res = await fetch('print-image', {
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
const imgPreview = document.getElementById('imgpreview');
let imgPreviewUrl = null;

imgFile.addEventListener('change', () => {
  if (imgPreviewUrl) URL.revokeObjectURL(imgPreviewUrl);
  const f = imgFile.files[0];
  if (!f) { imgPreview.style.display = 'none'; return; }
  imgPreviewUrl = URL.createObjectURL(f);
  imgPreview.src = imgPreviewUrl;
  imgPreview.style.display = 'block';
});

document.getElementById('imgsend').addEventListener('click', () => {
  const f = imgFile.files[0];
  if (!f) { imgStatus.textContent = 'Pick a file first.'; return; }
  sendImageBlob(f, imgStatus);
});

let camStream = null;
let camFacingMode = 'environment';
const video = document.getElementById('video');
const camStatus = document.getElementById('camstatus');
const camStatusDefault = camStatus.textContent;
const camToggle = document.getElementById('camtoggle');
const camToggleIcon = camToggle.querySelector('.material-icons');

function setCamToggleState(on) {
  camToggleIcon.textContent = on ? 'videocam_off' : 'videocam';
  const label = on ? 'Stop Camera' : 'Start Camera';
  camToggle.title = label;
  camToggle.setAttribute('aria-label', label);
}

async function startCamera() {
  try {
    camStream = await navigator.mediaDevices.getUserMedia({video: {facingMode: camFacingMode}});
    video.srcObject = camStream;
    video.style.display = 'block';
    camStatus.textContent = 'Camera on.';
    setCamToggleState(true);
  } catch (e) {
    camStatus.textContent = 'Camera failed: ' + e.message;
  }
}

function stopCamera() {
  if (camStream) {
    camStream.getTracks().forEach((t) => t.stop());
    camStream = null;
  }
  video.style.display = 'none';
  camStatus.textContent = camStatusDefault;
  setCamToggleState(false);
}

camToggle.addEventListener('click', () => {
  if (camStream) { stopCamera(); } else { startCamera(); }
});

document.getElementById('camswitch').addEventListener('click', () => {
  camFacingMode = camFacingMode === 'environment' ? 'user' : 'environment';
  if (camStream) {
    camStream.getTracks().forEach((t) => t.stop());
    camStream = null;
    startCamera();
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


LLM_SYSTEM_PROMPT = (
    "Answer as directly and briefly as possible — give only what's actually "
    "needed, nothing more. If the question has a one-word answer (e.g. "
    "'heads or tails'), answer with that one word. If it genuinely needs "
    "real content (e.g. a recipe or instructions), give the actual "
    "concrete content, not a vague description, but still as concise as "
    "you can make it. Your reply gets printed on a narrow thermal receipt "
    "printer, so: plain text only — no markdown, no asterisks, no "
    "headers, no emoji."
)
LLM_FONT_SIZE = 22  # smaller than the hand-typed default, since replies run longer
MAX_LLM_REPLY_CHARS = 1200  # hard cap so a runaway reply can't burn through paper/time


def generate_llm_reply(prompt: str) -> str:
    """Ask Pollinations.ai's free text endpoint for a short reply (no API key required)."""
    url = (
        "https://text.pollinations.ai/"
        + urllib.parse.quote(prompt, safe="")
        + "?system=" + urllib.parse.quote(LLM_SYSTEM_PROMPT, safe="")
    )
    req = urllib.request.Request(url, headers={"User-Agent": "m02-thermal-printer"})
    with urllib.request.urlopen(req, timeout=POLLINATIONS_TIMEOUT) as resp:
        reply = resp.read().decode("utf-8", errors="replace").strip()
    return reply[:MAX_LLM_REPLY_CHARS]


def do_print_llm_reply(prompt: str) -> None:
    reply = generate_llm_reply(prompt)
    wrapped = wrap_text(reply, font_size=LLM_FONT_SIZE)
    img = text_to_image(wrapped, font_size=LLM_FONT_SIZE)
    rows = image_to_rows(img, dither=False)
    with _print_lock:
        print_rows(rows, addr=Config.addr, density_level=Config.density)


PRINTER_STATUS_TIMEOUT = 8.0


def check_printer_connected(addr: str) -> bool:
    """Open and immediately close an RFCOMM connection — a liveness probe,
    not an actual print. There's no persistent connection to check: each
    print job opens its own socket and closes it when done, same as this."""
    s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    s.settimeout(PRINTER_STATUS_TIMEOUT)
    try:
        s.connect((addr, RFCOMM_CHANNEL))
        return True
    except OSError:
        return False
    finally:
        s.close()


def do_print_image(data: bytes) -> None:
    """Decode, print, and discard — the image bytes never touch disk."""
    img = Image.open(io.BytesIO(data))
    img.load()  # force decode now, while the BytesIO backing it is still alive
    img = ImageOps.exif_transpose(img)  # phone/webcam photos often carry rotation metadata
    rows = image_to_rows(img, dither=True)
    with _print_lock:
        print_rows(rows, addr=Config.addr, density_level=Config.density)


def configure(*, addr: str, font_size: int, density: int) -> None:
    Config.addr = addr
    Config.font_size = font_size
    Config.density = density


def page(req) -> None:
    req.send_body(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")


def printer_status(req) -> None:
    if not _print_lock.acquire(blocking=False):
        # A print job is actively using the connection right now — that
        # alone proves it's reachable, and a second connect attempt
        # would just collide with it over this printer's single link.
        req.send_json(200, {"connected": True, "busy": True})
        return
    try:
        connected = check_printer_connected(Config.addr)
    finally:
        _print_lock.release()
    req.send_json(200, {"connected": connected, "busy": False})


def print_text(req) -> None:
    raw = req.read_body()
    content_type = req.headers.get("Content-Type", "")

    text = None
    if "application/json" in content_type:
        try:
            text = json.loads(raw.decode("utf-8")).get("text")
        except (json.JSONDecodeError, UnicodeDecodeError):
            req.send_json(400, {"error": "invalid JSON body"})
            return
    else:
        form = parse_qs(raw.decode("utf-8", errors="replace"))
        text = form.get("text", [None])[0]

    if not text or not text.strip():
        req.send_json(400, {"error": "missing 'text'"})
        return
    if len(text) > MAX_TEXT_LENGTH:
        req.send_json(400, {"error": f"text too long (max {MAX_TEXT_LENGTH} chars)"})
        return

    try:
        do_print(text)
    except Exception as exc:  # noqa: BLE001 - report any failure to the client
        req.send_json(502, {"error": str(exc)})
        return

    req.send_json(200, {"ok": True})


def print_image(req) -> None:
    length = int(req.headers.get("Content-Length", 0))
    if length <= 0:
        req.send_json(400, {"error": "missing image body"})
        return
    if length > MAX_IMAGE_BYTES:
        req.send_json(400, {"error": f"image too large (max {MAX_IMAGE_BYTES // (1024 * 1024)}MB)"})
        return

    raw = req.rfile.read(length)

    try:
        do_print_image(raw)
    except UnidentifiedImageError:
        req.send_json(400, {"error": "not a recognizable image"})
        return
    except Exception as exc:  # noqa: BLE001 - report any failure to the client
        req.send_json(502, {"error": str(exc)})
        return
    finally:
        del raw  # drop the reference promptly; nothing here ever touches disk

    req.send_json(200, {"ok": True})


def lucky(req) -> None:
    raw = req.read_body()
    try:
        text = json.loads(raw.decode("utf-8")).get("text")
    except (json.JSONDecodeError, UnicodeDecodeError):
        req.send_json(400, {"error": "invalid JSON body"})
        return

    if not text or not text.strip():
        req.send_json(400, {"error": "missing 'text'"})
        return
    if len(text) > MAX_PROMPT_LENGTH:
        req.send_json(400, {"error": f"prompt too long (max {MAX_PROMPT_LENGTH} chars)"})
        return

    try:
        do_print_llm_reply(text)
    except urllib.error.HTTPError as exc:
        req.send_json(502, {"error": f"AI reply failed: HTTP {exc.code}"})
        return
    except (urllib.error.URLError, TimeoutError) as exc:
        req.send_json(502, {"error": f"AI reply failed: {exc}"})
        return
    except Exception as exc:  # noqa: BLE001 - report any failure to the client
        req.send_json(502, {"error": str(exc)})
        return

    req.send_json(200, {"ok": True})


ROUTES = {
    ("GET", "/"): page,
    ("GET", "/printer-status"): printer_status,
    ("POST", "/print"): print_text,
    ("POST", "/print-image"): print_image,
    ("POST", "/lucky"): lucky,
}

