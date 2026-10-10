# dumb-home-project

The small web apps running on the Raspberry Pi at home, served by **one Python
process** with only the standard library and Pillow — no Flask, no venv.

| URL | App | Code |
|---|---|---|
| `https://<pi>:8765/` | landing page | `server.py` |
| `https://<pi>:8765/printer/` | M02 thermal printer: text, images, webcam, "I'm Feeling Lucky" | `apps/printer/` |
| `https://<pi>:8765/rooms/` | room planner | `apps/rooms/` |
| `https://<pi>:8765/transit/` | BVG departures (Erkstraße, U Rathaus Neukölln) | `apps/transit/` |
| `http://<pi>:5001/` | the same departures, for the e-reader | `apps/transit/` |

No authentication — only run this on a trusted home network.

## Why port 5001 is special

The e-reader's app has `http://<pi>:5001/` (and `/api/departures`) baked in;
changing it means rebuilding the APK. So `server.py` keeps a second, plain-HTTP
listener on 5001 that serves exactly those two routes, with the same JSON as
the old Flask app. Two more things the e-reader depends on:

- `/api/departures` always answers `200` — the page only schedules its next
  refresh after a successful response, so an error would freeze the display.
- Requests are answered instantly from a cache, never waiting on the BVG API.
  The countdown is computed at response time from absolute departure times, so
  it's exact even if the cached data is a few seconds old. A request that finds
  the cache older than 10s triggers a background refresh for the next poll.
  Only after a minute without requests (e.g. the e-reader was off) does a
  request wait for fresh data, and nothing is polled while nobody's looking.

Everything else is on 8765 over HTTPS, because the printer's webcam tab needs a
secure context. The self-signed cert is generated on first start.

## Run

Requirements: Python 3.9+, Pillow (`sudo apt install python3-pil`), `openssl`,
and BlueZ for the printer.

```sh
python3 server.py
python3 server.py --http --port 8080 --transit-port 0   # local testing: plain HTTP, no 5001 listener
```

Room layouts (`rooms.json`) and the TLS cert live in `--data-dir`, by default
`~/.local/share/dumb-home-project/` — outside the repo, so a `git pull` never
touches them. Printer options: `--addr`, `--font-size`, `--density`.

## On the Raspberry Pi

```sh
git clone <this-repo> ~/dumb-home-project
cd ~/dumb-home-project
./install.sh     # installs + starts the dumb-home systemd service, retires m02-printer
```

`install.sh` stops the old `m02-printer` service. The old departures app on
port 5001 has to be stopped by hand first (the script checks and tells you
what's still listening).

Moving over the existing state:

```sh
mkdir -p ~/.local/share/dumb-home-project
# keep the printer's cert, so browsers don't warn again
cp ~/m02-thermal-printer/cert.pem ~/m02-thermal-printer/key.pem ~/.local/share/dumb-home-project/
# from the laptop: the room layouts
scp ~/development/room-planner/data.json <pi>:.local/share/dumb-home-project/rooms.json
```

After pushing changes, apply them on the Pi with `./deploy.sh` (`git pull` and
restart the service).

## Adding an app

Create `apps/<name>/` with a module that exposes `ROUTES`, a dict of
`{(method, path): function(req)}` with paths relative to the app's prefix, and
add it to `APPS` in `server.py`. Use relative URLs in the app's pages so they
work under the prefix. `req` is the request handler from `web.py`, with
`send_json`, `send_body`, `send_file`, `read_body` and `redirect` helpers.

## History

`apps/printer`, `apps/rooms` and `apps/transit` were merged in with their full
git history from `m02-thermal-printer`, `room-planner` and
[`alexehrlich/sonnenallez`](https://github.com/alexehrlich/sonnenallez).
