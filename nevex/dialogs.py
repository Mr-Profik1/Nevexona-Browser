"""Bookmarks / history / downloads windows and the settings dialog."""
from __future__ import annotations

import threading

from .webkit_compat import Gtk, WebKit2
from gi.repository import Gio, GLib, Pango

from . import ai, paths
from .urlutil import SEARCH_ENGINES


def _label(text, dim=False, bold=False, ellipsize=True):
    lab = Gtk.Label(label=text, xalign=0)
    if ellipsize:
        lab.set_ellipsize(Pango.EllipsizeMode.END)
    if dim:
        lab.get_style_context().add_class("nx-dim")
    if bold:
        lab.set_markup("<b>%s</b>" % GLib.markup_escape_text(text))
    return lab


class ListWindow(Gtk.Window):
    """Searchable list of (title, url) rows; used for bookmarks and history."""

    def __init__(self, parent, title, fetch, on_open, on_delete, on_clear=None):
        super().__init__(title=title, transient_for=parent)
        self.set_default_size(640, 480)
        self.fetch, self.on_open, self.on_delete, self.on_clear = fetch, on_open, on_delete, on_clear
        self.urls: list = []
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=8)
        self.add(box)
        self.search = Gtk.SearchEntry()
        self.search.connect("search-changed", lambda *_: self.refresh())
        box.pack_start(self.search, False, False, 0)
        self.listbox = Gtk.ListBox()
        self.listbox.connect("row-activated", self._activated)
        sw = Gtk.ScrolledWindow()
        sw.add(self.listbox)
        box.pack_start(sw, True, True, 0)
        row = Gtk.Box(spacing=6)
        box.pack_start(row, False, False, 0)
        b_open = Gtk.Button(label="Open in new tab")
        b_open.connect("clicked", lambda *_: self._open_selected())
        b_del = Gtk.Button(label="Remove")
        b_del.connect("clicked", lambda *_: self._delete_selected())
        row.pack_start(b_open, False, False, 0)
        row.pack_start(b_del, False, False, 0)
        if on_clear:
            b_clear = Gtk.Button(label="Clear all")
            b_clear.connect("clicked", self._clear)
            row.pack_end(b_clear, False, False, 0)
        self.refresh()
        self.show_all()

    def refresh(self):
        for child in self.listbox.get_children():
            self.listbox.remove(child)
        items = self.fetch(self.search.get_text())
        self.urls = [i["url"] for i in items]
        for i in items:
            vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=4)
            vb.pack_start(_label(i["title"] or i["url"], bold=True), False, False, 0)
            vb.pack_start(_label(i["url"], dim=True), False, False, 0)
            self.listbox.add(vb)
        if not items:
            self.listbox.add(_label("Nothing here yet.", dim=True))
        self.listbox.show_all()

    def _url_of(self, row):
        if row is None:
            return None
        idx = row.get_index()
        return self.urls[idx] if 0 <= idx < len(self.urls) else None

    def _activated(self, _lb, row):
        url = self._url_of(row)
        if url:
            self.on_open(url)

    def _open_selected(self):
        url = self._url_of(self.listbox.get_selected_row())
        if url:
            self.on_open(url)

    def _delete_selected(self):
        url = self._url_of(self.listbox.get_selected_row())
        if url:
            self.on_delete(url)
            self.refresh()

    def _clear(self, *_):
        dlg = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                buttons=Gtk.ButtonsType.OK_CANCEL, text="Remove everything in this list?")
        if dlg.run() == Gtk.ResponseType.OK:
            self.on_clear()
            self.refresh()
        dlg.destroy()


class DownloadsWindow(Gtk.Window):
    def __init__(self, parent, manager):
        super().__init__(title="Downloads", transient_for=parent)
        self.manager = manager
        self.set_default_size(560, 420)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=8)
        self.add(box)
        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        sw = Gtk.ScrolledWindow()
        sw.add(self.listbox)
        box.pack_start(sw, True, True, 0)
        row = Gtk.Box(spacing=6)
        box.pack_start(row, False, False, 0)
        b_folder = Gtk.Button(label="Open downloads folder")
        b_folder.connect("clicked", lambda *_: self._launch(GLib.filename_to_uri(paths.download_dir(), None)))
        b_clear = Gtk.Button(label="Clear finished")
        b_clear.connect("clicked", lambda *_: manager.clear_finished())
        row.pack_start(b_folder, False, False, 0)
        row.pack_end(b_clear, False, False, 0)
        self._pending = 0
        manager.listeners.append(self._schedule)
        self.connect("destroy", lambda *_: manager.listeners.remove(self._schedule)
                     if self._schedule in manager.listeners else None)
        self.refresh()
        self.show_all()

    def _schedule(self):  # throttle redraws to ~3/s
        if not self._pending:
            self._pending = GLib.timeout_add(300, self._tick)

    def _tick(self):
        self._pending = 0
        self.refresh()
        return False

    @staticmethod
    def _launch(uri):
        try:
            Gio.AppInfo.launch_default_for_uri(uri, None)
        except GLib.Error:
            pass

    def refresh(self):
        for child in self.listbox.get_children():
            self.listbox.remove(child)
        for item in self.manager.items:
            vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin=4)
            vb.pack_start(_label(item.filename, bold=True), False, False, 0)
            status = {"downloading": "%d%%" % int(item.progress * 100), "finished": "Finished",
                      "cancelled": "Cancelled", "failed": "Failed: " + item.error}[item.state]
            vb.pack_start(_label(status, dim=True), False, False, 0)
            if item.state == "downloading":
                bar = Gtk.ProgressBar()
                bar.set_fraction(item.progress)
                vb.pack_start(bar, False, False, 0)
                btn = Gtk.Button(label="Cancel")
                btn.connect("clicked", lambda _b, it=item: self.manager.cancel(it))
                vb.pack_start(btn, False, False, 0)
            elif item.state == "finished" and item.dest:
                btn = Gtk.Button(label="Open file")
                btn.connect("clicked", lambda _b, it=item: self._launch(GLib.filename_to_uri(it.dest, None)))
                vb.pack_start(btn, False, False, 0)
            self.listbox.add(vb)
        if not self.manager.items:
            self.listbox.add(_label("No downloads in this session.", dim=True))
        self.listbox.show_all()


class SettingsDialog(Gtk.Dialog):
    def __init__(self, parent, app):
        super().__init__(title="Settings", transient_for=parent, modal=True)
        self.app = app
        s = app.settings
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Save", Gtk.ResponseType.OK)
        grid = Gtk.Grid(column_spacing=10, row_spacing=8, margin=12)
        self.get_content_area().add(grid)
        r = 0

        def row(text, widget):
            nonlocal r
            grid.attach(Gtk.Label(label=text, xalign=1), 0, r, 1, 1)
            widget.set_hexpand(True)
            grid.attach(widget, 1, r, 1, 1)
            r += 1

        def heading(text):
            nonlocal r
            lab = Gtk.Label(xalign=0, margin_top=8)
            lab.set_markup("<b>%s</b>" % GLib.markup_escape_text(text))
            grid.attach(lab, 0, r, 2, 1)
            r += 1

        heading("Browser")
        self.homepage = Gtk.Entry(text=s.get("homepage"))
        row("Homepage", self.homepage)
        self.engine = Gtk.ComboBoxText()
        for key, (name, _a, _p) in SEARCH_ENGINES.items():
            self.engine.append(key, name)
        self.engine.set_active_id(s.get("search_engine"))
        row("Search engine", self.engine)
        self.restore = Gtk.Switch(active=s.get("restore_session"), halign=Gtk.Align.START)
        row("Restore tabs on start", self.restore)
        self.reduced = Gtk.Switch(active=s.get("reduced_memory"), halign=Gtk.Align.START)
        row("Reduced-memory mode", self.reduced)
        hint = _label("Disables WebGL, page cache and smooth scrolling, and unloads tabs "
                      "you have not used for a while. Fully applies after restart.", dim=True, ellipsize=False)
        hint.set_line_wrap(True)
        hint.set_max_width_chars(48)
        grid.attach(hint, 1, r, 1, 1)
        r += 1
        self.clear_status = _label("", dim=True)
        btn = Gtk.Button(label="Clear history and website data…", halign=Gtk.Align.START)
        btn.connect("clicked", self._clear_data)
        row("Privacy", btn)
        grid.attach(self.clear_status, 1, r, 1, 1)
        r += 1

        heading("AI assistant (optional, off by default)")
        self.ai_enabled = Gtk.Switch(active=s.get("ai_enabled"), halign=Gtk.Align.START)
        row("Enable AI assistant", self.ai_enabled)
        self.endpoint = Gtk.Entry(text=s.get("ai_endpoint"))
        self.endpoint.set_placeholder_text("https://your-provider.example/v1")
        row("API endpoint", self.endpoint)
        self.key = Gtk.Entry(visibility=False)
        self.key.set_text(app.api_keys.get())
        self.key.set_placeholder_text("API key (stored locally, file mode 0600)")
        row("API key", self.key)
        self.model = Gtk.ComboBoxText.new_with_entry()
        self.model.get_child().set_text(s.get("ai_model"))
        fetch = Gtk.Button(label="Fetch models")
        fetch.connect("clicked", self._fetch_models)
        mb = Gtk.Box(spacing=6)
        mb.pack_start(self.model, True, True, 0)
        mb.pack_start(fetch, False, False, 0)
        row("Model", mb)
        self.ai_status = _label("", dim=True, ellipsize=False)
        self.ai_status.set_line_wrap(True)
        self.ai_status.set_max_width_chars(48)
        grid.attach(self.ai_status, 1, r, 1, 1)
        self.show_all()

    def _clear_data(self, _btn):
        self.app.history.clear()
        try:
            ctx = self.app.persistent_context()
            ctx.get_website_data_manager().clear(WebKit2.WebsiteDataTypes.ALL, 0, None, None, None)
            self.clear_status.set_text("History, cookies and cache cleared.")
        except Exception as e:  # API differences between WebKitGTK versions
            self.clear_status.set_text("History cleared. Website data: %s" % e)

    def _fetch_models(self, _btn):
        endpoint, key = self.endpoint.get_text(), self.key.get_text().strip()
        self.ai_status.set_text("Fetching models…")

        def work():
            try:
                ids = ai.list_models(endpoint, key)
                GLib.idle_add(self._models_ok, ids)
            except ai.AIError as e:
                GLib.idle_add(self.ai_status.set_text, "Error: %s" % e)

        threading.Thread(target=work, daemon=True).start()

    def _models_ok(self, ids):
        current = self.model.get_child().get_text()
        self.model.remove_all()
        for i in ids:
            self.model.append_text(i)
        self.model.get_child().set_text(current or ids[0])
        self.ai_status.set_text("%d models available." % len(ids))

    def apply(self):
        s = self.app.settings
        s.set("homepage", self.homepage.get_text().strip() or "nevex:start")
        s.set("search_engine", self.engine.get_active_id() or "yandex")
        s.set("restore_session", self.restore.get_active())
        s.set("reduced_memory", self.reduced.get_active())
        s.set("ai_enabled", self.ai_enabled.get_active())
        s.set("ai_endpoint", self.endpoint.get_text().strip())
        s.set("ai_model", (self.model.get_child().get_text() or "").strip())
        s.save()
        self.app.api_keys.set(self.key.get_text())
