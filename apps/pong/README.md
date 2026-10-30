# Pong

Our 42 `ft_transcendence` project: online pong with a lobby, remote and local
matches, an AI opponent, tournaments and stats. It's a Django app with Channels;
the game runs server-side at 60 FPS and is streamed to the browsers over
WebSockets.

Unlike the other apps it can't be mounted into `server.py`, so it runs as its own
service, `dumb-home-pong`, on `https://<pi>:8443/`. The dumb-home landing page
links to it.

## How it was slimmed down for the Pi

The original was four Docker containers (nginx, Django with gunicorn + daphne,
Postgres, Redis). On the Pi (1 GB RAM, 32-bit ARM, no Docker) it's one process,
~60 MB of RAM:

| Before | Now | |
|---|---|---|
| nginx + gunicorn + daphne | **daphne** only, doing TLS itself | the ASGI app also serves plain HTTP; static files via whitenoise, uploads via a Django route |
| Postgres | **SQLite** (`pong.sqlite3`) | no Postgres-specific code |
| Redis channel layer | **in-memory** channel layer | only the consumers use it, all in the one daphne process |
| pygame | a small `Rect` class in `pong_game.py` | the server only used `Rect` and `colliderect` |
| Docker | a venv + systemd | |

Python packages with compiled parts (cryptography, Twisted, argon2, Pillow, …)
come from Debian's apt packages; only pure-Python ones are pip-installed (see
`requirements.txt`).

## Setup on the Pi

Needs dumb-home's TLS cert, so run the main `install.sh` first. Then:

```sh
cd ~/dumb-home-project/apps/pong
./install.sh
```

That installs the apt packages, creates `.venv`, writes fresh secrets to
`~/.local/share/dumb-home-project/pong.env` and starts the `dumb-home-pong`
service. `run.sh` runs migrations and creates the built-in users on each start.

Data lives in `~/.local/share/dumb-home-project/pong/` (database, avatars,
collected static files). Logs: `journalctl -u dumb-home-pong -f`.

## Users

- Make an account on the site, or play as a guest.
- `admin` (Django admin at `/admin/`), `AI_Ursula` (the AI opponent) and `Local`
  (the second player in local games) are created automatically. Their password
  is `USERS_ADMIN_PW` in `pong.env`.
- "Login with 42" needs a registered 42 intra OAuth app (`OAUTH_CLIENT_ID`,
  `OAUTH_CLIENT_SECRET`, `OAUTH_CALLBACK_URL` in `pong.env`); without one the
  button doesn't work.
