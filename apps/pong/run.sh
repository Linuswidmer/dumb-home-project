#!/bin/sh
# Start the pong server (used by the dumb-home-pong systemd service): prepare the
# data dir and database, then serve HTTP and WebSockets over TLS with daphne.
#
# It has to stay a single daphne process: the in-memory channel layer only
# connects players whose WebSockets are in the same process.
set -e
cd "$(dirname "$0")"

DATA="${DUMB_HOME_DATA:-$HOME/.local/share/dumb-home-project}"
export PONG_DATA_DIR="$DATA/pong"
# asgi.py imports the consumers before setting this itself, so it must come from outside.
export DJANGO_SETTINGS_MODULE=app_server.settings
set -a  # export everything from the env file (secret key, admin password, hosts)
. "$DATA/pong.env"
set +a

mkdir -p "$PONG_DATA_DIR/media"
cp -r --update=none media/. "$PONG_DATA_DIR/media/"  # default avatars; never overwrites uploads

PY=.venv/bin/python
$PY manage.py migrate --noinput
$PY manage.py collectstatic --noinput -v 0
$PY manage.py shell < create_default_users.py

# Reuses dumb-home's self-signed cert, so browsers that accepted it once are fine.
exec .venv/bin/daphne \
    -e "ssl:${PONG_PORT:-8443}:privateKey=$DATA/key.pem:certKey=$DATA/cert.pem" \
    app_server.asgi:application
