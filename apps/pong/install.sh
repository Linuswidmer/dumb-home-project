#!/bin/sh
# One-time setup of the pong server on the Raspberry Pi: system packages, a venv,
# fresh secrets, and the dumb-home-pong systemd service. Re-running it is harmless
# (it keeps existing secrets and data). Run the main ./install.sh first, which
# creates the TLS cert this reuses.
set -e
cd "$(dirname "$0")"
APP="$(pwd)"
DATA="$HOME/.local/share/dumb-home-project"

APT_PACKAGES="python3-venv python3-pil python3-cffi python3-argon2 python3-twisted python3-openssl
    python3-service-identity python3-autobahn python3-zope.interface python3-requests
    python3-requests-oauthlib python3-openid python3-jwt python3-defusedxml python3-dotenv
    python3-whitenoise"
# shellcheck disable=SC2086
sudo apt-get install -y -q $APT_PACKAGES

[ -d .venv ] || python3 -m venv --system-site-packages .venv
.venv/bin/pip install -q -r requirements.txt

if [ ! -f "$DATA/cert.pem" ]; then
    echo "No TLS cert in $DATA — run the main install.sh (or start dumb-home once) first." >&2
    exit 1
fi

# Fresh secrets for this host. Never reuse the ones committed in the old
# 42_transcendence repo: that repo is public.
mkdir -p "$DATA/pong"
if [ ! -f "$DATA/pong.env" ]; then
    (
        umask 077
        cat > "$DATA/pong.env" <<EOF
DJANGO_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')
# Password for the built-in users, including 'admin' (https://<pi>:8443/admin/).
USERS_ADMIN_PW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(12))')
# Home LAN only, reached by IP or hostname.
DJANGO_ALLOWED_HOSTS=*
EOF
    )
    echo "Wrote fresh secrets to $DATA/pong.env"
fi

sudo tee /etc/systemd/system/dumb-home-pong.service > /dev/null <<EOF
[Unit]
Description=dumb-home-project: pong (Django + daphne)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(id -un)
WorkingDirectory=$APP
Environment=PYTHONUNBUFFERED=1
ExecStart=/bin/sh $APP/run.sh
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable dumb-home-pong
sudo systemctl restart dumb-home-pong
echo "Pong is starting: https://$(hostname -I | cut -d' ' -f1):8443/  (logs: journalctl -u dumb-home-pong -f)"
