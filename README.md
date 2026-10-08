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

## GUI (`m02_gui.py`)

A small always-on-top-style GTK window for printing notes on the fly. Enter
inserts a newline like normal text editing; Ctrl+Enter sends the current text
to the printer and clears the box.

```sh
python3 m02_gui.py
python3 m02_gui.py --addr AA:BB:CC:DD:EE:FF --font-size 40 --density 3
```

Uses GTK3 via `python3-gi` (already present on most desktop Linux installs —
no pip packages needed).

## Web app (`m02_web.py`)

A tiny local web server so other people/devices on your network can send
print jobs too — a browser form at `/`, and a JSON endpoint at `POST /print`.
No authentication; only run this on a trusted home/LAN network.

```sh
python3 m02_web.py
# No TLS cert found, generating a self-signed one at .../cert.pem ...
# Serving on https://0.0.0.0:8765
#   (self-signed cert — your browser will warn once, click through to continue)
```

On first run it generates its own self-signed TLS certificate (via
`openssl`, into `cert.pem`/`key.pem` next to the script — gitignored, never
committed, one per host) and serves HTTPS by default. Your browser will show
a "not private" warning the first time — click Advanced → Proceed, it's
expected for a self-signed cert on a home server.

Open `https://<your-laptop-ip>:8765` in a browser (or `https://localhost:8765`
on the same machine). The page has three sections:

- **Text** — type and hit Ctrl+Enter or the Print button. Or click
  **"I'm Feeling Lucky!"** to send the text as a prompt to
  [Pollinations.ai](https://pollinations.ai) (free, no API key/signup — just
  an HTTP request) and print the AI-generated image instead. Takes up to
  ~30s; anonymous use is rate-limited to roughly one request per 15s and
  images carry a small watermark.
- **Image** — pick a file and print it.
- **Webcam** — start the camera, capture a frame, print it.

Uploaded/captured images are decoded, dithered, printed, and discarded —
**nothing is ever written to disk**, so there's no cleanup needed even on a
space-constrained device like a Raspberry Pi.

HTTPS exists specifically for the webcam section: browsers only allow camera
access (`getUserMedia`) on a *secure context* — `https://`, or
`http://localhost`/`127.0.0.1`. Over plain HTTP from another device
(`http://<lan-ip>:8765`), the camera button would fail. Pass `--http` to
opt back into plain HTTP (e.g. for quick local testing) if you don't need
the webcam feature from other devices.

Or send a print job directly:

```sh
curl -k -X POST https://localhost:8765/print \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello from curl!"}'

curl -k -X POST https://localhost:8765/print-image \
  -H "Content-Type: image/jpeg" \
  --data-binary @photo.jpg

curl -k -X POST https://localhost:8765/lucky \
  -H "Content-Type: application/json" \
  -d '{"text": "a cute robot cat drinking coffee"}'
```

(`-k` skips certificate verification for the self-signed cert — fine for
local/LAN use with `curl`; a browser just needs a one-time click-through
instead.)

Options: `--host` (default `0.0.0.0`), `--port` (default `8765`), `--http`
(serve plain HTTP instead), plus the same `--addr` / `--font-size` /
`--density` flags as the other scripts. Print
jobs are serialized (one at a time) even if multiple requests arrive at once.
Image uploads are capped at 15MB.

## Running as a service (e.g. on a Raspberry Pi)

```sh
sudo tee /etc/systemd/system/m02-printer.service > /dev/null <<'EOF'
[Unit]
Description=M02 thermal printer web app
After=bluetooth.target network.target

[Service]
Type=simple
User=<your-user>
WorkingDirectory=/home/<your-user>/m02-thermal-printer
ExecStart=/usr/bin/python3 m02_web.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now m02-printer
```

If the Bluetooth adapter shows `NotReady` when scanning, it's probably
rfkill-soft-blocked: `sudo rfkill unblock bluetooth && bluetoothctl power on`.

## Deploying updates

To pull and apply changes without re-copying files by hand, clone the repo
over SSH using a read-only deploy key:

```sh
ssh-keygen -t ed25519 -C "<host> deploy key for m02-thermal-printer" -f ~/.ssh/m02_deploy_key -N ""
cat ~/.ssh/m02_deploy_key.pub   # add as a read-only Deploy Key on the GitHub repo
```

```sh
# ~/.ssh/config
Host github.com-m02deploy
    HostName github.com
    User git
    IdentityFile ~/.ssh/m02_deploy_key
    IdentitiesOnly yes
```

```sh
git clone git@github.com-m02deploy:Linuswidmer/m02-thermal-printer.git ~/m02-thermal-printer
```

After pushing changes from your dev machine, apply them on the server with:

```sh
./deploy.sh
```

which runs `git pull` and restarts the `m02-printer` service. (Requires
passwordless `sudo systemctl restart m02-printer` for the deploying user, or
run it with `sudo ./deploy.sh` / enter your password when prompted.)

## Notes

- Text is rendered with DejaVu Sans at a fixed threshold (no dithering —
  dithering turns thin strokes into faint, unreliable dot patterns on thermal
  paper). Images are dithered with contrast boosted beforehand, since thermal
  printing tends to come out lighter than the source image.
- `PRINT_WIDTH = 384` dots is specific to the M02; other models in the family
  are wider (M02S/M02 Pro are 576).
