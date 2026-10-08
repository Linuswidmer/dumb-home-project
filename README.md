# m02-thermal-printer

Print text or images on a "Mr.in_M02" (Phomemo M02-family clone) Bluetooth
thermal printer from a Linux laptop, without the vendor app.

Talks directly to the printer over classic Bluetooth RFCOMM (SPP) — no
pairing/PIN required, no proprietary SDK, no BLE library. Only dependency is
Pillow, for rendering text/images into the raster format the printer expects.

## How it works

- **Transport**: classic Bluetooth SPP, RFCOMM channel 1. Python's stdlib
  `socket.AF_BLUETOOTH` / `BTPROTO_RFCOMM` talks to it directly — no pairing
  needed.
- **Protocol**: not ESC/POS text — a Phomemo "M02" vendor dialect: a few
  `\x1f\x11...` density/media setup commands, then a `GS v 0` raster bitmap
  command carrying a 1-bit-per-pixel, 384-dot-wide image. The printer ignores
  plain ASCII text; everything, including "text", gets rendered to a bitmap
  first. Protocol identified via the open-source
  [TiMini-Print](https://github.com/Dejniel/TiMini-Print) project, which has
  this exact printer in its device catalog.
- **Key quirk**: the printer silently drops raster/feed data that arrives
  faster than its thermal head can physically consume it, even though RFCOMM
  is a reliable stream — this showed up as truncated prints (image cut off
  partway) and feed commands being ignored. Fixed by pacing writes to one
  raster row (and one feed command) at a time with a short delay between each.

## Requirements

- Linux with BlueZ (`bluetoothd` running)
- Python 3 with Pillow (`python3-pil` via apt, or `pip install pillow`)
- The printer powered on and in range (no app/phone needed, and make sure no
  other device, like the vendor's phone app, is currently connected to it)

## Finding your printer's address

```sh
bluetoothctl --timeout 20 scan on | grep Device
```

Look for a device named `Mr.in_M02` (or similar — other printers in the same
family advertise as `M02`, `M02C`, etc.). Note its MAC address.

If you have a different printer in this family (M02S, M02X, M02 Pro, T02,
...), the wire protocol differs slightly (print width, feed scaling) — see
`timiniprint/data/printer_models.json` and `printer_profiles.json` in
TiMini-Print for the exact values to adapt `PRINT_WIDTH` and the density
table to your model.

## Usage

```sh
# Print text
python3 m02_print.py "Hello world"

# Print an image (resized to the printer's 384px width, dithered)
python3 m02_print.py --image photo.jpg

# Use a different printer address than the default baked into the script
python3 m02_print.py --addr AA:BB:CC:DD:EE:FF "Custom text"

# Options
python3 m02_print.py --font-size 40 "Bigger text"
python3 m02_print.py --density 2 "Lighter print"   # 1 (lightest) - 4 (darkest, default)
```

Update the `ADDR` constant at the top of `m02_print.py` to your printer's MAC
address (or pass `--addr` each time).

## Notes

- Text is rendered with DejaVu Sans at a fixed threshold (no dithering —
  dithering turns thin strokes into faint, unreliable dot patterns on thermal
  paper). Images are dithered with contrast boosted beforehand, since thermal
  printing tends to come out lighter than the source image.
- `PRINT_WIDTH = 384` dots is specific to the M02; other models in the family
  are wider (M02S/M02 Pro are 576).
