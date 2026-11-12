# Photo booth

`https://<pi>:8765/photobooth/`: turns any device with a camera (laptop,
tablet, phone) into a photo booth for the M02 thermal printer.

- A full-screen, mirrored, black-and-white live preview and one big shutter
  button. Then a 3-2-1 countdown with beeps, a flash and a shutter sound.
- **Single** prints one photo. **Strip of 4** takes four shots in a row and
  prints them as a classic booth strip (about 50s of printing).
- A review screen shows exactly how the dithered print will come out, with
  **Print** / **Retake**. An abandoned review discards itself after 90s.
- Every print gets a centred caption and the date and time underneath. Set
  the caption with `server.py --booth-caption "Lisa & Tom's party"`, or
  `--booth-caption ""` for the date only. The default is "Photobooth".
- **Space** / **Enter** takes a photo (and prints on the review screen), and
  **Esc** retakes. Arrow keys and Page Up/Down work too, so a cheap
  presentation clicker makes a wireless remote shutter.
- The fullscreen button and a screen wake lock make it suitable for leaving a
  tablet set up as a kiosk.

## How it works

The browser crops each frame to 3:2 and composes the frames into one white
strip (`index.html`). It previews the thermal result with the same contrast,
brightness and Floyd–Steinberg steps as `image_to_rows()`, then sends one
JPEG to `POST print`. The server dithers it with `keep_white=True`, so the
borders stay blank paper, adds the caption and prints it. Nothing is written
to disk.

Prints go through `apps/printer`'s lock and settings (`--addr`, `--density`),
so a booth print and a print from `/printer/` queue up instead of colliding
on the printer's single Bluetooth link. The page needs HTTPS for the camera,
which the shared self-signed cert already provides.
