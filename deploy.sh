#!/bin/sh
# Pull the latest code and restart the systemd service.
# Run this on the Raspberry Pi after pushing changes.
set -e
cd "$(dirname "$0")"
git pull
sudo systemctl restart dumb-home
echo "Deployed and restarted dumb-home."
