#!/bin/sh
# Pull the latest code and restart the systemd services.
# Run this on the Raspberry Pi after pushing changes.
set -e
cd "$(dirname "$0")"
git pull
sudo systemctl restart dumb-home
echo "Deployed and restarted dumb-home."

# Pong runs as its own service once apps/pong/install.sh has set it up.
if [ -f /etc/systemd/system/dumb-home-pong.service ]; then
    apps/pong/.venv/bin/pip install -q -r apps/pong/requirements.txt
    sudo systemctl restart dumb-home-pong
    echo "Restarted dumb-home-pong (it takes ~20s to come up)."
fi
