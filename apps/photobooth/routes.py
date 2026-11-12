"""Photo booth: a full-screen webcam preview, a big shutter button, a 3-2-1
countdown, and a printed photo (or a classic four-shot strip) with a caption
and the date underneath.

It prints through the printer app's settings and lock, so a booth print and
a print from /printer/ queue up instead of fighting over the printer's
single Bluetooth link.
"""
from __future__ import annotations

import io
import json
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from apps.printer import routes as printer
from apps.printer.m02_print import FONT_PATH, PRINT_WIDTH, image_to_rows, print_rows

PAGE_PATH = Path(__file__).parent / "index.html"
MAX_IMAGE_BYTES = 15 * 1024 * 1024  # handled in memory only, never written to disk
MAX_HEIGHT_RATIO = 8  # image height / width; guards against a runaway paper roll
CAPTION_FONT_SIZE = 22  # keep in sync with renderPreview() in index.html


class Config:
    caption: str = "Photobooth"


def configure(*, caption: str) -> None:
    Config.caption = caption


def caption_rows() -> list[bytes]:
    """The caption and date under the photos, each line centred."""
    stamp = datetime.now().strftime("%d.%m.%Y  %H:%M")
    lines = [Config.caption, stamp] if Config.caption else [stamp]
    font = ImageFont.truetype(FONT_PATH, CAPTION_FONT_SIZE)
    line_height, margin = CAPTION_FONT_SIZE + 6, 8
    img = Image.new("L", (PRINT_WIDTH, margin * 2 + line_height * len(lines)), 255)
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((PRINT_WIDTH / 2, margin + i * line_height), line, font=font, fill=0, anchor="mt")
    return image_to_rows(img, top_padding=0, dither=False)


def do_print_photo(data: bytes) -> None:
    """Decode, print, and discard — the image bytes never touch disk."""
    img = Image.open(io.BytesIO(data))
    img.load()
    img = ImageOps.exif_transpose(img)
    if img.height > img.width * MAX_HEIGHT_RATIO:
        raise ValueError("image is too tall to print")
    # keep_white: the white borders between strip frames stay blank paper.
    rows = image_to_rows(img, dither=True, keep_white=True) + caption_rows()
    with printer._print_lock:
        print_rows(rows, addr=printer.Config.addr, density_level=printer.Config.density)


def page(req) -> None:
    html = PAGE_PATH.read_text(encoding="utf-8").replace("{{CAPTION}}", json.dumps(Config.caption))
    req.send_body(200, html.encode("utf-8"), "text/html; charset=utf-8")


def print_photo(req) -> None:
    length = int(req.headers.get("Content-Length", 0))
    if length <= 0:
        req.send_json(400, {"error": "missing image body"})
        return
    if length > MAX_IMAGE_BYTES:
        req.send_json(400, {"error": f"image too large (max {MAX_IMAGE_BYTES // (1024 * 1024)}MB)"})
        return
    raw = req.rfile.read(length)
    try:
        do_print_photo(raw)
    except UnidentifiedImageError:
        req.send_json(400, {"error": "not a recognizable image"})
        return
    except ValueError as exc:
        req.send_json(400, {"error": str(exc)})
        return
    except Exception as exc:  # noqa: BLE001 - report any failure to the client
        req.send_json(502, {"error": str(exc)})
        return
    finally:
        del raw
    req.send_json(200, {"ok": True})


ROUTES = {
    ("GET", "/"): page,
    ("GET", "/printer-status"): printer.printer_status,
    ("POST", "/print"): print_photo,
}
