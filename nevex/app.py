"""Gtk.Application: owns storage, web contexts, downloads and windows."""
from __future__ import annotations

import argparse
import os
import signal
import sys

from .webkit_compat import Gtk, WebKit2
from gi.repository import Gio, GLib

from . import APP_ID, APP_NAME, __version__, paths
from .downloads import DownloadManager
from .storage import ApiKeyStore, Bookmarks, History, SessionStore, Settings
from .theme import apply_theme
from .urlutil import resolve_input
from .window import BrowserWindow


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nevex-browser", description="NEVEX AI - lightweight web browser")
    p.add_argument("urls", nargs="*", help="addresses, search terms or file paths to open in tabs")
    p.add_argument("--private", action="store_true", help="open a private window")
    p.add_argument("--profile", metavar="DIR", help="keep all settings and data in DIR (separate instance)")
    p.add_argument("--reduced-memory", action="store_true", help="force reduced-memory mode for this run")
    p.add_argument("--version", action="version", version="%s %s" % (APP_NAME, __version__))
    return p


class NevexApp(Gtk.Application):
    def __init__(self, non_unique: bool = False):
        flags = Gio.ApplicationFlags.HANDLES_COMMAND_LINE
        if non_unique:
            flags |= Gio.ApplicationFlags.NON_UNIQUE
        super().__init__(application_id=APP_ID, flags=flags)
        self.session_owner = None
        self._persistent_ctx = None
        self._started = False

    # ---- lifecycle -----------------------------------------------------------------
    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.settings = Settings()
        self.api_keys = ApiKeyStore()
        self.bookmarks = Bookmarks()
        self.history = History()
        self.session = SessionStore()
        self.downloads = DownloadManager()
        apply_theme()
        for sig in (signal.SIGINT, signal.SIGTERM):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, self._on_signal)

    def do_activate(self):
        pass  # windows are created in do_command_line

    def do_command_line(self, cl):
        args = cl.get_arguments()[1:]
        try:
            ns, _unknown = build_parser().parse_known_args(args)
            urls, private = ns.urls, ns.private
        except SystemExit:
            urls, private = [], False
        urls = [u for u in (resolve_input(u, self.settings.get("search_engine")) for u in urls) if u]

        wins = self.get_windows()
        if private:
            win = self.open_window(private=True)
            for u in urls:
                win.add_tab(u, activate=True)
        elif not wins:
            win = self.open_window()
            if urls:
                for u in urls:
                    win.add_tab(u, activate=True)
            else:
                entries, active = self.session.load() if self.settings.get("restore_session") else ([], 0)
                if entries:
                    win.restore_tabs(entries, active)
                else:
                    win.add_tab(activate=True)
        else:
            win = wins[0]
            for u in urls:
                win.add_tab(u, activate=True)
            if not urls:
                win.add_tab(activate=True, focus_url=True)
        win.present()
        return 0

    def do_shutdown(self):
        self.downloads.cancel_all()
        self.history.close()
        Gtk.Application.do_shutdown(self)

    def _on_signal(self):
        self.quit_all()
        return GLib.SOURCE_REMOVE

    # ---- helpers used by windows ------------------------------------------------------
    def reduced(self) -> bool:
        return bool(os.environ.get("NEVEX_REDUCED_MEMORY")) or self.settings.get("reduced_memory")

    def open_window(self, private: bool = False) -> BrowserWindow:
        win = BrowserWindow(self, private=private)
        if not private and self.session_owner is None:
            self.session_owner = win
        win.show()
        return win

    def window_closing(self, win) -> None:
        if win is self.session_owner:
            self.session_owner = next(
                (w for w in self.get_windows() if w is not win and isinstance(w, BrowserWindow) and not w.private),
                None,
            )

    def quit_all(self) -> None:
        for w in list(self.get_windows()):
            if isinstance(w, BrowserWindow):
                w.close()  # runs delete-event: saves session, frees web views
        self.quit()

    def settings_changed(self) -> None:
        for w in self.get_windows():
            if isinstance(w, BrowserWindow):
                w.refresh_after_settings()
        if self._persistent_ctx is not None:
            self._apply_cache_model(self._persistent_ctx)

    # ---- WebKit contexts (created lazily on first tab) -----------------------------------------
    def _apply_cache_model(self, ctx) -> None:
        try:
            ctx.set_cache_model(
                WebKit2.CacheModel.DOCUMENT_VIEWER if self.reduced() else WebKit2.CacheModel.WEB_BROWSER
            )
        except Exception:
            pass

    def persistent_context(self):
        if self._persistent_ctx is None:
            ctx = None
            try:
                wdm = WebKit2.WebsiteDataManager(
                    base_data_directory=paths.data_dir(), base_cache_directory=paths.cache_dir()
                )
                ctx = WebKit2.WebContext.new_with_website_data_manager(wdm)
            except Exception:
                ctx = WebKit2.WebContext.get_default()
            try:
                ctx.get_cookie_manager().set_persistent_storage(
                    os.path.join(paths.data_dir(), "cookies.sqlite"), WebKit2.CookiePersistentStorage.SQLITE
                )
            except Exception:
                pass
            self._finish_context(ctx)
            self._persistent_ctx = ctx
        return self._persistent_ctx

    def private_context(self):
        ctx = WebKit2.WebContext.new_ephemeral()
        self._finish_context(ctx)
        return ctx

    def _finish_context(self, ctx) -> None:
        self._apply_cache_model(ctx)
        try:
            ctx.set_spell_checking_enabled(False)
        except Exception:
            pass
        self.downloads.attach(ctx)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ns = build_parser().parse_args(argv)  # handles --help / --version before GTK starts
    if ns.profile:
        os.environ["NEVEX_PROFILE"] = os.path.abspath(ns.profile)
    if ns.reduced_memory:
        os.environ["NEVEX_REDUCED_MEMORY"] = "1"
    GLib.set_prgname("nevex-browser")
    GLib.set_application_name(APP_NAME)
    app = NevexApp(non_unique=bool(ns.profile))
    return app.run([sys.argv[0]] + argv)
