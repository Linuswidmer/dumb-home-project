#!/usr/bin/env python3
"""A small GTK window for printing text to the M02 thermal printer live.

Enter inserts a newline, like normal text editing. Ctrl+Enter sends the
current text to the printer and clears the box for the next note.
"""
from __future__ import annotations

import argparse
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

from m02_print import ADDR, image_to_rows, print_rows, text_to_image

IDLE_STATUS = "Enter = newline · Ctrl+Enter = print"


class PrinterWindow(Gtk.Window):
    def __init__(self, addr: str, font_size: int, density: int):
        super().__init__(title="M02 Printer")
        self.addr = addr
        self.font_size = font_size
        self.density = density

        self.set_default_size(420, 220)
        self.set_border_width(8)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add(vbox)

        self.textview = Gtk.TextView()
        self.textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.textview.connect("key-press-event", self.on_key_press)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.textview)
        scroll.set_vexpand(True)
        vbox.pack_start(scroll, True, True, 0)

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.status = Gtk.Label(label=IDLE_STATUS)
        self.status.set_halign(Gtk.Align.START)
        hbox.pack_start(self.status, True, True, 0)
        send_btn = Gtk.Button(label="Print")
        send_btn.connect("clicked", lambda *_: self.send())
        hbox.pack_start(send_btn, False, False, 0)
        vbox.pack_start(hbox, False, False, 0)

        self.connect("destroy", Gtk.main_quit)
        self.textview.grab_focus()

    def on_key_press(self, _widget, event) -> bool:
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if event.state & Gdk.ModifierType.CONTROL_MASK:
                self.send()
                return True  # swallow the keypress so no newline is inserted
        return False

    def send(self) -> None:
        buf = self.textview.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        if not text.strip():
            return
        self.set_status("Printing…")
        self.textview.set_sensitive(False)
        threading.Thread(target=self._print_job, args=(text.rstrip("\n"),), daemon=True).start()

    def _print_job(self, text: str) -> None:
        try:
            img = text_to_image(text, font_size=self.font_size)
            rows = image_to_rows(img, dither=False)
            print_rows(rows, addr=self.addr, density_level=self.density)
            GLib.idle_add(self._on_done, True, None)
        except Exception as exc:  # noqa: BLE001 - report any failure to the GUI
            GLib.idle_add(self._on_done, False, str(exc))

    def _on_done(self, ok: bool, error: str | None) -> bool:
        if ok:
            self.textview.get_buffer().set_text("")
            self.set_status(f"Printed. {IDLE_STATUS}")
        else:
            self.set_status(f"Print failed: {error}")
        self.textview.set_sensitive(True)
        self.textview.grab_focus()
        return False

    def set_status(self, text: str) -> None:
        self.status.set_text(text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Live GUI for the M02 thermal printer")
    parser.add_argument("--addr", default=ADDR, help="Printer Bluetooth MAC address")
    parser.add_argument("--font-size", type=int, default=32)
    parser.add_argument("--density", type=int, default=4, choices=(1, 2, 3, 4))
    args = parser.parse_args()

    win = PrinterWindow(addr=args.addr, font_size=args.font_size, density=args.density)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
