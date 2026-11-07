"""AI chat sidebar. Created only when the user opens it; talks only to the
endpoint the user configured. Chat history lives in memory only."""
from __future__ import annotations

import threading

from .webkit_compat import Gtk
from gi.repository import GLib

from . import ai

MAX_TURNS = 20


class AISidebar(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.win = win
        self.get_style_context().add_class("nx-sidebar")
        self.set_size_request(340, -1)
        self.history: list = []
        self.token = 0  # bumped on clear/cancel so stale callbacks are ignored
        self.cancel_ev = None
        self.streaming = False

        head = Gtk.Box(spacing=4)
        title = Gtk.Label(label="NEVEX AI", xalign=0)
        title.get_style_context().add_class("nx-title")
        head.pack_start(title, True, True, 0)
        self.model_label = Gtk.Label(xalign=1)
        self.model_label.get_style_context().add_class("nx-dim")
        head.pack_start(self.model_label, False, False, 0)
        b_clear = Gtk.Button.new_from_icon_name("edit-clear-all-symbolic", Gtk.IconSize.MENU)
        b_clear.set_tooltip_text("Clear conversation")
        b_clear.connect("clicked", lambda *_: self.clear())
        b_close = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU)
        b_close.set_tooltip_text("Close sidebar")
        b_close.connect("clicked", lambda *_: win.set_sidebar_visible(False))
        head.pack_start(b_clear, False, False, 0)
        head.pack_start(b_close, False, False, 0)
        self.pack_start(head, False, False, 0)

        self.view = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                                 left_margin=6, right_margin=6, top_margin=6, bottom_margin=6)
        buf = self.view.get_buffer()
        buf.create_tag("user", foreground="#ff9a4d", weight=700)
        buf.create_tag("assistant", foreground="#e6e6e6")
        buf.create_tag("error", foreground="#ff6b6b")
        buf.create_mark("end", buf.get_end_iter(), False)
        sw = Gtk.ScrolledWindow()
        sw.add(self.view)
        self.pack_start(sw, True, True, 0)

        self.status = Gtk.Label(xalign=0, wrap=True)
        self.status.set_max_width_chars(40)
        self.status.get_style_context().add_class("nx-error")
        self.pack_start(self.status, False, False, 0)

        row = Gtk.Box(spacing=4)
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Ask something…")
        self.entry.connect("activate", lambda *_: self.send())
        self.btn = Gtk.Button(label="Send")
        self.btn.get_style_context().add_class("nx-accent")
        self.btn.connect("clicked", lambda *_: self.on_button())
        row.pack_start(self.entry, True, True, 0)
        row.pack_start(self.btn, False, False, 0)
        self.pack_start(row, False, False, 0)
        self.refresh_config()
        self.show_all()

    # ---- configuration -------------------------------------------------
    def config(self):
        s = self.win.app.settings
        return s.get("ai_endpoint"), self.win.app.api_keys.get(), s.get("ai_model")

    def refresh_config(self):
        endpoint, _key, model = self.config()
        self.model_label.set_text(model or "no model")
        if not endpoint or not model:
            self.status.set_text("Set the API endpoint and model in Settings to start chatting.")
        elif not self.streaming:
            self.status.set_text("")

    # ---- chat ------------------------------------------------------------
    def clear(self):
        self.cancel()
        self.history.clear()
        self.view.get_buffer().set_text("")
        self.refresh_config()

    def cancel(self):
        self.token += 1
        if self.cancel_ev is not None:
            self.cancel_ev.set()
        self.streaming = False
        self.btn.set_label("Send")

    def on_button(self):
        if self.streaming:
            self.cancel()
        else:
            self.send()

    def _append(self, text, tag):
        buf = self.view.get_buffer()
        buf.insert_with_tags_by_name(buf.get_end_iter(), text, tag)
        self.view.scroll_mark_onscreen(buf.get_mark("end"))

    def send(self):
        text = self.entry.get_text().strip()
        if not text or self.streaming:
            return
        endpoint, key, model = self.config()
        try:
            ai.normalize_endpoint(endpoint)
            if not model:
                raise ai.AIError("No model selected. Choose one in Settings.")
        except ai.AIError as e:
            self.status.set_text(str(e))
            return
        self.entry.set_text("")
        self.status.set_text("")
        self.history.append({"role": "user", "content": text})
        self.history[:] = self.history[-MAX_TURNS * 2:]
        self._append("You: " + text + "\n", "user")
        self._append("AI: ", "user")
        messages = [{"role": "system", "content": ai.SYSTEM_PROMPT}] + list(self.history)
        self.token += 1
        token = self.token
        self.cancel_ev = threading.Event()
        cancel = self.cancel_ev
        self.streaming = True
        self.btn.set_label("Stop")
        self._reply = ""

        def work():
            err = None
            try:
                for piece in ai.stream_chat(endpoint, key, model, messages, cancel=cancel):
                    GLib.idle_add(self._chunk, piece, token)
            except ai.AIError as e:
                err = str(e)
            except Exception as e:  # never let a worker thread die silently
                err = "Unexpected error: %s" % e
            GLib.idle_add(self._done, err, token)

        threading.Thread(target=work, daemon=True).start()

    def _chunk(self, piece, token):
        if token == self.token:
            self._reply += piece
            self._append(piece, "assistant")
        return False

    def _done(self, err, token):
        if token != self.token:
            return False
        self.streaming = False
        self.btn.set_label("Send")
        self._append("\n\n", "assistant")
        if self._reply:
            self.history.append({"role": "assistant", "content": self._reply})
        elif err and self.history and self.history[-1]["role"] == "user":
            self.history.pop()  # keep the transcript alternating user/assistant
        if err:
            self.status.set_text(err)
        return False
