"""Browser window and tabs."""
from __future__ import annotations

import time

from .webkit_compat import Gtk, WebKit2
from gi.repository import Gio, GLib, Pango

from . import APP_NAME
from .dialogs import DownloadsWindow, ListWindow, SettingsDialog
from .pages import error_page_html, start_page_html
from .sidebar import AISidebar
from .urlutil import START_URL, display_url, is_web_url, resolve_input

# Errors that are part of normal operation (user pressed stop, link became a download).
_IGNORED_ERRORS = {("webkit-network-error-quark", 302), ("webkit-policy-error-quark", 102)}


def configure_webview(view, reduced: bool) -> None:
    s = view.get_settings()
    props = {
        "enable-developer-extras": False,
        "enable-write-console-messages-to-stdout": False,
        "javascript-can-open-windows-automatically": False,
        "allow-file-access-from-file-urls": False,
        "allow-universal-access-from-file-urls": False,
        "enable-smooth-scrolling": not reduced,
        "enable-page-cache": not reduced,
        "enable-webgl": not reduced,
    }
    for name, value in props.items():
        try:  # property set differs slightly between WebKitGTK versions
            s.set_property(name, value)
        except (TypeError, ValueError):
            pass


class Tab:
    def __init__(self, win, url: str = "", title: str = ""):
        self.win = win
        self.url = url or START_URL
        self.title = title
        self.is_start = self.url == START_URL
        self.loading = False
        self.progress = 0.0
        self.last_active = time.monotonic()
        self.webview = None
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.box.show()

        self.label = Gtk.Label(label=self._label_text(), xalign=0)
        self.label.set_ellipsize(Pango.EllipsizeMode.END)
        self.label.set_width_chars(12)
        self.label.set_max_width_chars(22)
        close = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU)
        close.get_style_context().add_class("nx-tabbtn")
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.set_focus_on_click(False)
        close.set_tooltip_text("Close tab")
        close.connect("clicked", lambda *_: win.close_tab(self))
        hb = Gtk.Box(spacing=2)
        hb.pack_start(self.label, True, True, 0)
        hb.pack_start(close, False, False, 0)
        hb.show_all()
        self.header = Gtk.EventBox()
        self.header.set_visible_window(False)
        self.header.add(hb)
        self.header.connect("button-press-event", self._header_click)
        self.header.show()

    def _header_click(self, _w, event):
        if event.button == 2:
            self.win.close_tab(self)
            return True
        return False

    def _label_text(self) -> str:
        return self.title or display_url(self.url) or "New Tab"

    def set_title(self, title: str) -> None:
        self.title = title or ""
        text = self._label_text()
        self.label.set_text(text)
        self.header.set_tooltip_text(text)

    # ---- web view lifecycle (lazy) -----------------------------------------
    def ensure_webview(self, related=None, load: bool = True):
        if self.webview is not None:
            return self.webview
        if related is not None:
            wv = WebKit2.WebView(related_view=related)
        else:
            wv = WebKit2.WebView(web_context=self.win.get_context())
        configure_webview(wv, self.win.app.reduced())
        wv.connect("notify::title", self._on_title)
        wv.connect("notify::uri", self._on_uri)
        wv.connect("notify::estimated-load-progress", self._on_progress)
        wv.connect("load-changed", self._on_load_changed)
        wv.connect("load-failed", self._on_load_failed)
        wv.connect("create", self._on_create)
        wv.connect("close", lambda *_: self.win.close_tab(self))
        wv.connect("permission-request", self._on_permission)
        try:
            wv.connect("web-process-terminated", self._on_crashed)
        except TypeError:
            pass
        self.webview = wv
        self.box.pack_start(wv, True, True, 0)
        wv.show()
        if load and related is None:
            self.load(self.url)
        return wv

    def discard_webview(self) -> None:
        """Free the web view (and its renderer memory) but keep the tab."""
        wv, self.webview = self.webview, None
        if wv is not None:
            self.loading = False
            self.progress = 0.0
            wv.destroy()

    def destroy(self) -> None:
        self.discard_webview()
        self.box.destroy()

    # ---- navigation ------------------------------------------------------------
    def load(self, url: str) -> None:
        self.url = url or START_URL
        wv = self.ensure_webview(load=False)
        if self.url == START_URL:
            self.is_start = True
            wv.load_html(self.win.start_html(), None)
        else:
            self.is_start = False
            wv.load_uri(self.url)

    def current_uri(self) -> str:
        return display_url(self.webview.get_uri() if self.webview else self.url) if not self.is_start else ""

    def page_url(self) -> str:
        """The real URL of the page ('' for the start page)."""
        if self.is_start:
            return ""
        return (self.webview.get_uri() if self.webview else None) or self.url

    # ---- signal handlers ----------------------------------------------------------
    def _on_title(self, wv, _p):
        if not self.is_start:
            self.set_title(wv.get_title() or "")
            self.win.on_tab_state_changed(self)

    def _on_uri(self, wv, _p):
        uri = wv.get_uri() or ""
        if uri == "about:blank" and self.is_start:
            return
        self.is_start = False
        self.url = uri or self.url
        self.win.on_tab_state_changed(self)
        self.win.schedule_session_save()

    def _on_progress(self, wv, _p):
        self.progress = wv.get_estimated_load_progress()
        self.win.on_tab_state_changed(self)

    def _on_load_changed(self, wv, event):
        if event == WebKit2.LoadEvent.STARTED:
            self.loading = True
        elif event == WebKit2.LoadEvent.FINISHED:
            self.loading = False
            uri = wv.get_uri()
            if is_web_url(uri) and not self.win.private:
                self.win.app.history.add(uri, wv.get_title() or "")
        self.win.on_tab_state_changed(self)

    def _on_load_failed(self, wv, _event, uri, error):
        if (error.domain, error.code) in _IGNORED_ERRORS:
            return False
        self.is_start = False
        wv.load_alternate_html(error_page_html(uri, error.message, error.code), uri, None)
        return True

    def _on_crashed(self, wv, _reason):
        uri = self.url if not self.is_start else ""
        wv.load_alternate_html(
            error_page_html(uri or "about:blank", "The page's process stopped unexpectedly "
                            "(possibly out of memory). Reload to try again."), uri or "about:blank", None)

    def _on_create(self, wv, _nav_action):
        tab = self.win.add_tab("", activate=True, related=wv)
        return tab.webview

    def _on_permission(self, _wv, request):
        request.deny()  # camera, microphone, location, notifications: always denied
        return True


class BrowserWindow(Gtk.ApplicationWindow):
    def __init__(self, app, private: bool = False):
        super().__init__(application=app)
        self.app = app
        self.private = private
        self.tabs: dict = {}  # tab.box -> Tab
        self._current: Tab | None = None
        self._ctx = None
        self._restoring = False
        self._shut_down = False
        self._save_source = 0
        self._hibernate_source = 0
        self.closed: list = []
        self.sidebar: AISidebar | None = None
        self.set_default_size(1100, 720)
        self.set_icon_name("nevex-browser")
        self._build()
        self._update_title()
        self.connect("delete-event", self._on_delete)
        self.refresh_after_settings()

    # ---- construction --------------------------------------------------------------
    def _icon_button(self, icon, tip, callback):
        b = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.SMALL_TOOLBAR)
        b.set_tooltip_text(tip)
        b.set_focus_on_click(False)
        b.connect("clicked", lambda *_: callback())
        return b

    def _build(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.get_style_context().add_class("nx-root")
        self.add(root)

        bar = Gtk.Box(spacing=3)
        bar.get_style_context().add_class("nx-toolbar")
        self.b_back = self._icon_button("go-previous-symbolic", "Back (Alt+Left)", self.go_back)
        self.b_fwd = self._icon_button("go-next-symbolic", "Forward (Alt+Right)", self.go_forward)
        self.b_reload = self._icon_button("view-refresh-symbolic", "Reload (F5)", self.reload_or_stop)
        self.b_home = self._icon_button("go-home-symbolic", "Home (Alt+Home)", self.go_home)
        for b in (self.b_back, self.b_fwd, self.b_reload, self.b_home):
            bar.pack_start(b, False, False, 0)
        self.url_entry = Gtk.Entry()
        self.url_entry.get_style_context().add_class("nx-url")
        self.url_entry.set_placeholder_text("Search or enter address")
        self.url_entry.connect("activate", lambda e: self.navigate(e.get_text()))
        self.url_entry.connect("focus-in-event", lambda e, _ev: GLib.idle_add(e.select_region, 0, -1) and False)
        bar.pack_start(self.url_entry, True, True, 4)
        self.b_star = self._icon_button("non-starred-symbolic", "Bookmark this page (Ctrl+D)", self.toggle_bookmark)
        self.b_newtab = self._icon_button("tab-new-symbolic", "New tab (Ctrl+T)", lambda: self.add_tab(activate=True))
        self.b_ai = self._icon_button("user-available-symbolic", "AI assistant (Ctrl+Shift+A)", self.toggle_sidebar)
        for b in (self.b_star, self.b_newtab, self.b_ai):
            bar.pack_start(b, False, False, 0)
        menu_btn = Gtk.MenuButton()
        menu_btn.set_image(Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.SMALL_TOOLBAR))
        menu_btn.set_menu_model(self._menu_model())
        bar.pack_start(menu_btn, False, False, 0)
        root.pack_start(bar, False, False, 0)

        self.progress = Gtk.ProgressBar()
        self.progress.get_style_context().add_class("nx-progress")
        root.pack_start(self.progress, False, False, 0)

        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        root.pack_start(self.paned, True, True, 0)
        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        self.notebook.set_show_border(False)
        self.notebook.connect("switch-page", self._on_switch_page)
        self.notebook.connect("page-reordered", lambda *_: self.schedule_session_save())
        self.paned.pack1(self.notebook, True, False)
        root.show_all()
        self.progress.hide()
        self._add_actions()

    def _menu_model(self):
        m = Gio.Menu()
        s1 = Gio.Menu()
        s1.append("New tab", "win.new-tab")
        s1.append("New private window", "win.new-private-window")
        s1.append("Reopen closed tab", "win.reopen-tab")
        m.append_section(None, s1)
        s2 = Gio.Menu()
        s2.append("Bookmarks", "win.bookmarks")
        s2.append("History", "win.history")
        s2.append("Downloads", "win.downloads")
        m.append_section(None, s2)
        s3 = Gio.Menu()
        s3.append("Zoom in", "win.zoom-in")
        s3.append("Zoom out", "win.zoom-out")
        s3.append("Reset zoom", "win.zoom-reset")
        m.append_section(None, s3)
        s4 = Gio.Menu()
        s4.append("AI assistant", "win.toggle-ai")
        s4.append("Settings", "win.settings")
        s4.append("Quit", "win.quit")
        m.append_section(None, s4)
        return m

    def _add_actions(self):
        table = {
            "new-tab": (lambda: self.add_tab(activate=True, focus_url=True), ["<Control>t"]),
            "close-tab": (lambda: self.close_tab(self._current), ["<Control>w"]),
            "reopen-tab": (self.reopen_tab, ["<Control><Shift>t"]),
            "new-private-window": (lambda: self.app.open_window(private=True), ["<Control><Shift>p"]),
            "focus-url": (self.focus_url, ["<Control>l", "F6"]),
            "reload": (self.reload_or_stop, ["F5", "<Control>r"]),
            "back": (self.go_back, ["<Alt>Left"]),
            "forward": (self.go_forward, ["<Alt>Right"]),
            "home": (self.go_home, ["<Alt>Home"]),
            "bookmark": (self.toggle_bookmark, ["<Control>d"]),
            "bookmarks": (self.show_bookmarks, ["<Control><Shift>o"]),
            "history": (self.show_history, ["<Control>h"]),
            "downloads": (self.show_downloads, ["<Control>j"]),
            "settings": (self.show_settings, ["<Control>comma"]),
            "toggle-ai": (self.toggle_sidebar, ["<Control><Shift>a"]),
            "next-tab": (lambda: self._cycle_tab(1), ["<Control>Tab"]),
            "prev-tab": (lambda: self._cycle_tab(-1), ["<Control><Shift>Tab", "<Control>ISO_Left_Tab"]),
            "zoom-in": (lambda: self._zoom(+0.1), ["<Control>plus", "<Control>equal", "<Control>KP_Add"]),
            "zoom-out": (lambda: self._zoom(-0.1), ["<Control>minus", "<Control>KP_Subtract"]),
            "zoom-reset": (lambda: self._zoom(0), ["<Control>0", "<Control>KP_0"]),
            "quit": (self.app.quit_all, ["<Control>q"]),
        }
        for name, (fn, accels) in table.items():
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", lambda _a, _p, f=fn: f())
            self.add_action(act)
            self.app.set_accels_for_action("win." + name, accels)

    # ---- context & pages ---------------------------------------------------------------
    def get_context(self):
        if self._ctx is None:
            self._ctx = self.app.private_context() if self.private else self.app.persistent_context()
        return self._ctx

    def start_html(self) -> str:
        s = self.app.settings
        bm = [] if self.private else self.app.bookmarks.all()
        return start_page_html(s.get("search_engine"), bm, self.private)

    # ---- tabs ------------------------------------------------------------------------------
    def current_tab(self):
        return self._current

    def add_tab(self, url: str = "", activate: bool = True, related=None, lazy: bool = False,
                title: str = "", focus_url: bool = False) -> Tab:
        tab = Tab(self, url, title)
        if related is not None:  # window.open()/target=_blank popup: not the start page
            tab.is_start = False
            tab.url = ""
        self.tabs[tab.box] = tab
        idx = self.notebook.append_page(tab.box, tab.header)
        self.notebook.set_tab_reorderable(tab.box, True)
        if related is not None:
            tab.ensure_webview(related=related)
        if activate:
            self.notebook.set_current_page(idx)
            if self._current is not tab:
                self._activate_tab(tab)
        if not lazy and activate and related is None:
            tab.ensure_webview()
        if focus_url and tab.is_start:
            self.focus_url()
        self.schedule_session_save()
        return tab

    def _ordered_tabs(self) -> list:
        return [self.tabs[self.notebook.get_nth_page(i)] for i in range(self.notebook.get_n_pages())]

    def _on_switch_page(self, _nb, page, _idx):
        tab = self.tabs.get(page)
        if tab is not None:
            self._activate_tab(tab)

    def _activate_tab(self, tab: Tab) -> None:
        self._current = tab
        tab.last_active = time.monotonic()
        if not self._restoring:
            tab.ensure_webview()  # lazy: restored tabs only load when first shown
        self.on_tab_state_changed(tab, force_url=True)
        self.schedule_session_save()

    def _cycle_tab(self, step: int) -> None:
        n = self.notebook.get_n_pages()
        if n:
            self.notebook.set_current_page((self.notebook.get_current_page() + step) % n)

    def close_tab(self, tab) -> None:
        if tab is None or tab.box not in self.tabs:
            return
        if len(self.tabs) == 1:
            self.close()  # closing the last tab closes the window (session is saved by delete-event)
            return
        if tab.url and tab.url != START_URL and not self.private:
            self.closed.append((tab.page_url() or tab.url, tab.title))
            del self.closed[:-10]
        idx = self.notebook.page_num(tab.box)
        del self.tabs[tab.box]
        if tab is self._current:
            self._current = None
        self.notebook.remove_page(idx)
        tab.destroy()
        cur = self.notebook.get_nth_page(self.notebook.get_current_page())
        if cur in self.tabs and self._current is not self.tabs[cur]:
            self._activate_tab(self.tabs[cur])
        self.schedule_session_save()

    def reopen_tab(self) -> None:
        if self.closed:
            url, title = self.closed.pop()
            self.add_tab(url, title=title)

    # ---- navigation actions ----------------------------------------------------------------------
    def navigate(self, text: str) -> None:
        url = resolve_input(text, self.app.settings.get("search_engine"))
        if not url:
            return
        tab = self._current or self.add_tab(activate=True)
        tab.load(url)
        if tab.webview is not None:
            tab.webview.grab_focus()

    def go_back(self):
        wv = self._current.webview if self._current else None
        if wv is not None and wv.can_go_back():
            wv.go_back()

    def go_forward(self):
        wv = self._current.webview if self._current else None
        if wv is not None and wv.can_go_forward():
            wv.go_forward()

    def reload_or_stop(self):
        tab = self._current
        if tab is None or tab.webview is None:
            return
        if tab.loading:
            tab.webview.stop_loading()
        elif tab.is_start:
            tab.load(START_URL)
        else:
            tab.webview.reload()

    def go_home(self):
        home = self.app.settings.get("homepage") or START_URL
        self.navigate(home)

    def focus_url(self):
        self.url_entry.grab_focus()

    def _zoom(self, delta: float) -> None:
        wv = self._current.webview if self._current else None
        if wv is None:
            return
        wv.set_zoom_level(1.0 if delta == 0 else max(0.3, min(4.0, wv.get_zoom_level() + delta)))

    # ---- bookmarks & windows -----------------------------------------------------------------------
    def toggle_bookmark(self):
        tab = self._current
        url = tab.page_url() if tab else ""
        if not is_web_url(url):
            return
        self.app.bookmarks.toggle(url, tab.title or url)
        self.on_tab_state_changed(tab)

    def _open_in_new_tab(self, url):
        self.add_tab(url, activate=True)

    def show_bookmarks(self):
        bm = self.app.bookmarks
        w = ListWindow(self, "Bookmarks", bm.search, self._open_in_new_tab, lambda u: (bm.remove(u), self.on_tab_state_changed(self._current)))
        w.present()

    def show_history(self):
        if self.private:
            return
        h = self.app.history
        ListWindow(self, "History", lambda q: h.recent(q), self._open_in_new_tab, h.delete, h.clear).present()

    def show_downloads(self):
        DownloadsWindow(self, self.app.downloads).present()

    def show_settings(self):
        dlg = SettingsDialog(self, self.app)
        if dlg.run() == Gtk.ResponseType.OK:
            try:
                dlg.apply()
            except (TypeError, KeyError, OSError) as e:
                err = Gtk.MessageDialog(transient_for=dlg, modal=True, message_type=Gtk.MessageType.ERROR,
                                        buttons=Gtk.ButtonsType.CLOSE, text="Could not save settings: %s" % e)
                err.run()
                err.destroy()
            self.app.settings_changed()
        dlg.destroy()

    # ---- AI sidebar (created lazily, only on demand) ------------------------------------------------------
    def toggle_sidebar(self):
        if not self.app.settings.get("ai_enabled"):
            self.show_settings()
            return
        self.set_sidebar_visible(self.sidebar is None)

    def set_sidebar_visible(self, visible: bool) -> None:
        if visible and self.sidebar is None:
            self.sidebar = AISidebar(self)
            self.paned.pack2(self.sidebar, False, False)
            width = self.get_allocated_width()
            if width > 700:
                self.paned.set_position(width - 350)
            self.sidebar.entry.grab_focus()
        elif not visible and self.sidebar is not None:
            self.sidebar.cancel()
            self.paned.remove(self.sidebar)
            self.sidebar.destroy()
            self.sidebar = None

    # ---- UI state ----------------------------------------------------------------------------------------------
    def on_tab_state_changed(self, tab, force_url: bool = False) -> None:
        if tab is not self._current:
            return
        wv = tab.webview
        self.b_back.set_sensitive(bool(wv and wv.can_go_back()))
        self.b_fwd.set_sensitive(bool(wv and wv.can_go_forward()))
        self.b_reload.set_image(Gtk.Image.new_from_icon_name(
            "process-stop-symbolic" if tab.loading else "view-refresh-symbolic", Gtk.IconSize.SMALL_TOOLBAR))
        self.b_reload.set_tooltip_text("Stop" if tab.loading else "Reload (F5)")
        if force_url or not self.url_entry.has_focus():
            self.url_entry.set_text(tab.current_uri())
        page = tab.page_url()
        starred = bool(page) and self.app.bookmarks.contains(page)
        self.b_star.set_image(Gtk.Image.new_from_icon_name(
            "starred-symbolic" if starred else "non-starred-symbolic", Gtk.IconSize.SMALL_TOOLBAR))
        self.b_star.get_style_context().remove_class("nx-on")
        if starred:
            self.b_star.get_style_context().add_class("nx-on")
        if tab.loading and 0.0 < tab.progress < 1.0:
            self.progress.set_fraction(tab.progress)
            self.progress.show()
        else:
            self.progress.hide()
        self._update_title()

    def _update_title(self) -> None:
        tab = self._current
        title = (tab.title if tab and tab.title else "") or APP_NAME
        suffix = " (Private)" if self.private else ""
        self.set_title("%s — %s%s" % (title, APP_NAME, suffix) if title != APP_NAME else APP_NAME + suffix)

    def refresh_after_settings(self) -> None:
        """Apply settings that can change while running."""
        self.b_ai.set_visible(self.app.settings.get("ai_enabled"))
        if not self.app.settings.get("ai_enabled"):
            self.set_sidebar_visible(False)
        elif self.sidebar is not None:
            self.sidebar.refresh_config()
        reduced = self.app.reduced()
        for tab in self.tabs.values():
            if tab.webview is not None:
                configure_webview(tab.webview, reduced)
        if reduced and not self._hibernate_source:
            self._hibernate_source = GLib.timeout_add_seconds(60, self._hibernate_tick)
        elif not reduced and self._hibernate_source:
            GLib.source_remove(self._hibernate_source)
            self._hibernate_source = 0
        if self.private:
            self.b_star.set_tooltip_text("Bookmark this page (Ctrl+D)")

    def _hibernate_tick(self) -> bool:
        """Reduced-memory mode: unload web views of tabs not used for a while."""
        limit = max(1, self.app.settings.get("hibernate_minutes")) * 60
        now = time.monotonic()
        for tab in self.tabs.values():
            if tab is self._current or tab.webview is None or tab.loading:
                continue
            if now - tab.last_active < limit:
                continue
            playing = getattr(tab.webview, "is_playing_audio", lambda: False)()
            if not playing:
                tab.url = tab.page_url() or tab.url
                tab.discard_webview()
        return True

    # ---- session -----------------------------------------------------------------------------------------------------
    def schedule_session_save(self) -> None:
        if self.private or self._restoring or self._shut_down or self._save_source or self.app.session_owner is not self:
            return
        self._save_source = GLib.timeout_add(1500, self._save_session_cb)

    def _save_session_cb(self) -> bool:
        self._save_source = 0
        self.save_session()
        return False

    def save_session(self) -> None:
        if self.private or self.app.session_owner is not self or not self.tabs:
            return
        tabs = self._ordered_tabs()
        entries = [{"url": t.page_url() or START_URL, "title": t.title} for t in tabs]
        try:
            self.app.session.save(entries, max(0, self.notebook.get_current_page()))
        except OSError:
            pass

    def restore_tabs(self, entries: list, active: int) -> None:
        self._restoring = True
        try:
            for e in entries:
                self.add_tab(e["url"], activate=False, lazy=True, title=e.get("title", ""))
            self.notebook.set_current_page(active)
        finally:
            self._restoring = False
        page = self.notebook.get_nth_page(self.notebook.get_current_page())
        self._activate_tab(self.tabs[page])

    # ---- shutdown --------------------------------------------------------------------------------------------------------
    def shutdown(self) -> None:
        """Save the session and free all web views. Safe to call more than once."""
        if self._shut_down:
            return
        self._shut_down = True
        for attr in ("_save_source", "_hibernate_source"):
            if getattr(self, attr):
                GLib.source_remove(getattr(self, attr))
                setattr(self, attr, 0)
        self.save_session()
        self.app.window_closing(self)
        self.set_sidebar_visible(False)
        for tab in list(self.tabs.values()):
            tab.destroy()
        self.tabs.clear()
        self._current = None

    def _on_delete(self, _w, _ev) -> bool:
        self.shutdown()
        return False
