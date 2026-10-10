#!/bin/sh
# Pull the latest code and restart the systemd service.
# Run this on the deployment host (e.g. the Raspberry Pi) after pushing changes.
set -e
cd "$(dirname "$0")"
git pull
sudo systemctl restart m02-printer
echo "Deployed and restarted m02-printer."
