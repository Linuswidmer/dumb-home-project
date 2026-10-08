#!/usr/bin/env python3
"""Print text or images on a Phomemo M02 / "Mr.in_M02" thermal printer over
classic Bluetooth (RFCOMM/SPP), no vendor app required.

Protocol reverse-engineered by the TiMini-Print project
(https://github.com/Dejniel/TiMini-Print) — see its
timiniprint/protocol/families/phomemo_esc/{core,compact}.py.

Usage:
    python3 m02_print.py "Hello world"
    python3 m02_print.py --image photo.jpg
    python3 m02_print.py --addr AA:BB:CC:DD:EE:FF "Custom text"
"""
from __future__ import annotations

import argparse
import socket
import time

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

ADDR = "DC:0D:30:C8:8F:F9"   # Mr.in_M02
RFCOMM_CHANNEL = 1
PRINT_WIDTH = 384            # dots, fixed for the M02
ROW_DELAY = 0.04             # seconds between each raster row write — see note below

# The printer's thermal head physically fires and advances one raster row at
# a time. Sending the image data faster than it can consume it (even over a
# reliable RFCOMM stream) causes it to silently drop the tail of the image —
# confirmed experimentally: bursty/chunked sends truncated after only a few
# rows, while pacing writes to one row every ~40ms printed cleanly in full.

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

_INIT = b"\x1b\x40"
_DENSITY_PREFIX = b"\x1f\x11\x02"
_DENSITY_COEFFICIENT = b"\x1f\x11\x37"
_MEDIA = b"\x1f\x11"
_UNCOMPRESSED = b"\x1f\x11\x35\x00"
_FEED = b"\x1b\x64\x02"
_EXIT_FEED = b"\x1b\x64\xff"  # ESC d 255: feed 255 lines, repeated to eject the page past the slot
_EXIT_FEED_REPEATS = 2
_EXIT_FEED_DELAY = 0.3        # commands sent back-to-back without a delay get silently dropped
_MEDIA_PLAIN = 0x0B
_DENSITY_LEVELS = ((1, 100), (2, 100), (4, 100), (4, 150))  # index by level 1-4


def build_header(*, density_level: int = 4) -> bytes:
    density, coefficient = _DENSITY_LEVELS[max(1, min(4, density_level)) - 1]
    header = bytearray()
    header += _INIT
    header += _DENSITY_PREFIX + bytes([density])
    header += _DENSITY_COEFFICIENT + bytes([coefficient])
    header += _MEDIA + bytes([_MEDIA_PLAIN])
    header += _UNCOMPRESSED
    return bytes(header)


def build_raster_header(pixels_1bit_rows: list[bytes]) -> bytes:
    width_bytes = len(pixels_1bit_rows[0]) if pixels_1bit_rows else (PRINT_WIDTH + 7) // 8
    height = len(pixels_1bit_rows)
    return (
        bytes((0x1D, 0x76, 0x30, 0x00))
        + width_bytes.to_bytes(2, "little")
        + height.to_bytes(2, "little")
    )

def pack_row(bits: list[int]) -> bytes:
    """Pack a row of 0/1 pixel values into bytes, MSB-first."""
    out = bytearray()
    for i in range(0, len(bits), 8):
        chunk = bits[i:i + 8]
        chunk += [0] * (8 - len(chunk))
        value = 0
        for bit, pix in enumerate(chunk):
            if pix:
                value |= 1 << (7 - bit)
        out.append(value)
    return bytes(out)


def image_to_rows(img: Image.Image, *, top_padding: int = 4, dither: bool = True) -> list[bytes]:
    """Convert a PIL image to packed 1-bit rows (resized to width=384), with blank top padding.

    Dithering suits photos but turns thin text strokes into sparse, faint dot
    patterns that don't fire reliably at low thermal density — use a plain
    threshold (dither=False) for text.
    """
    if img.width != PRINT_WIDTH:
        new_height = max(1, round(img.height * PRINT_WIDTH / img.width))
        img = img.resize((PRINT_WIDTH, new_height), Image.LANCZOS)
    img = img.convert("L")
    if dither:
        # Thermal dithering tends to print lighter than the source image —
        # darken midtones so grays come out as recognizably gray, not faint.
        img = ImageEnhance.Contrast(img).enhance(1.4)
        img = ImageEnhance.Brightness(img).enhance(0.8)
    bw = img.convert("1", dither=Image.FLOYDSTEINBERG if dither else Image.NONE)

    rows: list[bytes] = []
    blank_row = pack_row([0] * PRINT_WIDTH)
    rows.extend([blank_row] * top_padding)

    px = bw.load()
    for y in range(bw.height):
        bits = [1 if px[x, y] == 0 else 0 for x in range(bw.width)]  # black pixel -> 1
        rows.append(pack_row(bits))
    return rows


def text_to_image(text: str, *, font_size: int = 32, margin: int = 8) -> Image.Image:
    font = ImageFont.truetype(FONT_PATH, font_size)
    lines = text.splitlines() or [""]

    tmp = Image.new("L", (1, 1))
    draw = ImageDraw.Draw(tmp)
    line_heights = []
    max_line_width = 0
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_heights.append(bbox[3] - bbox[1])
        max_line_width = max(max_line_width, bbox[2] - bbox[0])

    line_spacing = 6
    total_height = sum(line_heights) + line_spacing * (len(lines) - 1) + 2 * margin

    img = Image.new("L", (PRINT_WIDTH, total_height), color=255)
    draw = ImageDraw.Draw(img)
    y = margin
    for line, lh in zip(lines, line_heights):
        draw.text((margin, y), line, font=font, fill=0)
        y += lh + line_spacing
    return img


def print_rows(
    rows: list[bytes],
    *,
    addr: str = ADDR,
    channel: int = RFCOMM_CHANNEL,
    density_level: int = 4,
    row_delay: float = ROW_DELAY,
) -> None:
    s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    s.settimeout(10)
    try:
        s.connect((addr, channel))
        s.sendall(build_header(density_level=density_level))
        s.sendall(build_raster_header(rows))
        for row in rows:
            s.sendall(row)
            time.sleep(row_delay)
        s.sendall(_FEED * 2)
        time.sleep(_EXIT_FEED_DELAY)
        for _ in range(_EXIT_FEED_REPEATS):
            s.sendall(_EXIT_FEED)
            time.sleep(_EXIT_FEED_DELAY)
        time.sleep(0.5)  # let the printer drain its buffer before we close the socket
    finally:
        s.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Print to a Phomemo M02 / Mr.in_M02 thermal printer")
    parser.add_argument("text", nargs="?", help="Text to print")
    parser.add_argument("--image", help="Path to an image file to print instead of text")
    parser.add_argument("--addr", default=ADDR, help="Printer Bluetooth MAC address")
    parser.add_argument("--font-size", type=int, default=32)
    parser.add_argument("--density", type=int, default=4, choices=(1, 2, 3, 4))
    args = parser.parse_args()

    if args.image:
        img = Image.open(args.image)
        dither = True
    elif args.text is not None:
        img = text_to_image(args.text, font_size=args.font_size)
        dither = False
    else:
        parser.error("Provide text or --image")

    rows = image_to_rows(img, dither=dither)
    print_rows(rows, addr=args.addr, density_level=args.density)
    print(f"Sent {len(rows)} raster rows to {args.addr}")


if __name__ == "__main__":
    main()
