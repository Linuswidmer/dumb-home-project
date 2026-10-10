#!/bin/sh
# One-time setup on the Raspberry Pi: install the dumb-home systemd service
# (running as the current user from this checkout) and start it, replacing
# the old m02-printer service. Re-running it is harmless.
set -e
cd "$(dirname "$0")"
DIR="$(pwd)"

sudo tee /etc/systemd/system/dumb-home.service > /dev/null <<EOF
[Unit]
Description=dumb-home-project (printer, room planner, departures)
After=bluetooth.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(id -un)
WorkingDirectory=$DIR
ExecStart=/usr/bin/python3 -u server.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload

# The old printer service holds port 8765 (and so does dumb-home on a re-run).
sudo systemctl disable --now m02-printer 2>/dev/null || true
sudo systemctl stop dumb-home 2>/dev/null || true

# The old departures app holds port 5001; it wasn't a known service, so it
# has to be stopped by hand.
for port in 8765 5001; do
    if sudo ss -ltnpH "sport = :$port" | grep -q .; then
        echo "Port $port is still in use — stop whatever is listening there first, then re-run:" >&2
        sudo ss -ltnpH "sport = :$port" >&2
        exit 1
    fi
done

sudo systemctl enable --now dumb-home
echo "dumb-home is running: https://$(hostname -I | cut -d' ' -f1):8765/"
