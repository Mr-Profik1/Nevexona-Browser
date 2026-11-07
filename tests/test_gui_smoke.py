"""End-to-end checks against real WebKitGTK. Skipped when GTK/WebKit or a display is missing.

Run with:  xvfb-run -a python3 -m pytest tests/test_gui_smoke.py -v
"""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

try:
    from nevex import webkit_compat  # noqa: F401
except (ImportError, ValueError) as exc:  # no GTK / WebKit typelibs
    pytest.skip("GTK/WebKit not available: %s" % exc, allow_module_level=True)

if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
    pytest.skip("no display (use xvfb-run)", allow_module_level=True)

from gi.repository import GLib  # noqa: E402


def page(title, body=""):
    return ("<!doctype html><title>%s</title><body><h1>%s</h1>%s</body>" % (title, title, body)).encode()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/dl":
            data = b"hello download"
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", 'attachment; filename="../evil name.bin"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        titles = {"/": "Page One", "/two": "Page Two"}
        data = page(titles.get(self.path, "Other"))
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture(scope="module")
def base():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % srv.server_port
    srv.shutdown()


def pump(cond, timeout=25.0):
    ctx = GLib.MainContext.default()
    end = time.time() + timeout
    while time.time() < end:
        while ctx.pending():
            ctx.iteration(False)
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    root = tmp_path_factory.mktemp("profile")
    os.environ["NEVEX_PROFILE"] = str(root)
    os.environ["NEVEX_DOWNLOAD_DIR"] = str(root / "downloads")
    from nevex.app import NevexApp

    a = NevexApp(non_unique=True)
    a.register(None)  # runs do_startup
    yield a
    a.do_shutdown()


def close_window(win):
    """Gtk.Window.close() is asynchronous; wait until the delete-event has been handled."""
    close_window(win)
    assert pump(lambda: win.tabs == {}), "window did not shut down"


def title_is(tab, text):
    return lambda: tab.webview is not None and tab.webview.get_title() == text


def test_ai_is_off_by_default(app):
    win = app.open_window()
    assert app.settings.get("ai_enabled") is False
    assert not win.b_ai.get_visible()
    assert win.sidebar is None
    close_window(win)


def test_start_page_renders(app):
    win = app.open_window()
    tab = win.add_tab(activate=True)
    assert pump(title_is(tab, "NEVEX AI"))
    close_window(win)


def test_navigation_back_forward_reload(app, base):
    win = app.open_window()
    tab = win.add_tab(base + "/", activate=True)
    assert pump(title_is(tab, "Page One"))
    win.navigate(base + "/two")
    assert pump(title_is(tab, "Page Two"))
    assert win.b_back.get_sensitive()
    win.go_back()
    assert pump(title_is(tab, "Page One"))
    win.go_forward()
    assert pump(title_is(tab, "Page Two"))
    win.reload_or_stop()
    assert pump(lambda: not tab.loading and tab.webview.get_title() == "Page Two")
    close_window(win)


def test_address_bar_search_uses_yandex(app):
    from nevex.urlutil import resolve_input

    assert resolve_input("hello", app.settings.get("search_engine")).startswith("https://yandex.ru/search/")


def test_tabs_open_close_and_lazy_restore(app, base):
    win = app.open_window()
    win.add_tab(base + "/", activate=True)
    win.add_tab(base + "/two", activate=True)
    win.add_tab(base + "/other", activate=True)
    assert len(win.tabs) == 3
    win.close_tab(win.current_tab())
    assert len(win.tabs) == 2
    win.reopen_tab()
    assert len(win.tabs) == 3
    close_window(win)

    win2 = app.open_window()
    win2.restore_tabs([{"url": base + "/", "title": ""}, {"url": base + "/two", "title": ""},
                       {"url": base + "/other", "title": ""}], 1)
    live = [t for t in win2._ordered_tabs() if t.webview is not None]
    assert len(live) == 1, "only the active tab should have a web view"
    assert win2.current_tab() is live[0]
    win2.notebook.set_current_page(2)
    assert pump(lambda: win2.current_tab().webview is not None)
    close_window(win2)


def test_bookmarks_and_history(app, base):
    win = app.open_window()
    tab = win.add_tab(base + "/", activate=True)
    assert pump(title_is(tab, "Page One"))
    assert pump(lambda: any(r["url"].startswith(base) for r in app.history.recent()))
    win.toggle_bookmark()
    assert app.bookmarks.contains(base + "/")
    win.toggle_bookmark()
    assert not app.bookmarks.contains(base + "/")
    close_window(win)


def test_private_window_records_no_history(app, base):
    app.history.clear()
    win = app.open_window(private=True)
    tab = win.add_tab(base + "/two", activate=True)
    assert pump(title_is(tab, "Page Two"))
    time.sleep(0.3)
    pump(lambda: False, 0.3)
    assert app.history.recent() == []
    close_window(win)


def test_error_page_for_unreachable_host(app):
    win = app.open_window()
    tab = win.add_tab("http://127.0.0.1:1/", activate=True)
    events = []
    tab.webview.connect("load-failed", lambda wv, ev, uri, err: events.append(("failed", err.domain, err.code, err.message)))
    tab.webview.connect("load-changed", lambda wv, ev: events.append(("changed", ev.value_nick)))
    ok = pump(title_is(tab, "Cannot open page"))
    assert ok, "title=%r uri=%r loading=%r is_start=%r events=%r" % (
        tab.webview.get_title(), tab.webview.get_uri(), tab.loading, tab.is_start, events)
    close_window(win)


def test_download_saved_safely(app, base):
    dl_dir = os.environ["NEVEX_DOWNLOAD_DIR"]
    win = app.open_window()
    tab = win.add_tab(base + "/", activate=True)
    assert pump(title_is(tab, "Page One"))
    win.navigate(base + "/dl")
    assert pump(lambda: app.downloads.items and app.downloads.items[0].state != "downloading")
    item = app.downloads.items[0]
    assert item.state == "finished", item.error
    assert os.path.dirname(item.dest) == dl_dir  # path traversal in filename was neutralised
    with open(item.dest, "rb") as f:
        assert f.read() == b"hello download"
    close_window(win)


def test_ai_sidebar_only_created_on_demand(app):
    app.settings.set("ai_enabled", True)
    win = app.open_window()
    assert win.b_ai.get_visible() and win.sidebar is None
    win.set_sidebar_visible(True)
    assert win.sidebar is not None
    win.set_sidebar_visible(False)
    assert win.sidebar is None
    app.settings.set("ai_enabled", False)
    close_window(win)


def test_shutdown_saves_session_and_frees_views(app, base):
    win = app.open_window()
    app.session_owner = win
    win.add_tab(base + "/", activate=True)
    win.add_tab(base + "/two", activate=True)
    assert pump(lambda: win.current_tab().webview.get_title() == "Page Two")
    close_window(win)
    with open(app.session.path) as f:
        data = json.load(f)
    assert [t["url"] for t in data["tabs"]] == [base + "/", base + "/two"]
    assert data["active"] == 1
    assert win.tabs == {}


def test_quit_all_writes_session_immediately(app, base):
    """Ctrl+Q path: the session must be saved before the main loop stops (runs last)."""
    win = app.open_window()
    app.session_owner = win
    win.add_tab(base + "/two", activate=True)
    app.quit_all()  # no main-loop iteration in between
    with open(app.session.path) as f:
        data = json.load(f)
    assert [t["url"] for t in data["tabs"]][-1] == base + "/two"
