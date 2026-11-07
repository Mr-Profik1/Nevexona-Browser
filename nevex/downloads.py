"""Download manager built on WebKit2 download objects."""
from __future__ import annotations

import os

from gi.repository import GLib

from . import paths
from .fsutil import sanitize_filename, unique_path


class DownloadItem:
    def __init__(self, download):
        self.download = download
        self.filename = "…"
        self.dest = None
        self.state = "downloading"  # downloading | finished | failed | cancelled
        self.progress = 0.0
        self.error = ""
        self.cancelled = False


class DownloadManager:
    def __init__(self):
        self.items: list = []
        self.listeners: list = []

    def attach(self, context) -> None:
        context.connect("download-started", self._on_started)

    def _notify(self) -> None:
        for cb in list(self.listeners):
            try:
                cb()
            except Exception:
                pass

    def _on_started(self, _ctx, download) -> None:
        item = DownloadItem(download)
        self.items.insert(0, item)
        del self.items[100:]
        download.connect("decide-destination", self._decide, item)
        download.connect("notify::estimated-progress", self._progress, item)
        download.connect("finished", self._finished, item)
        download.connect("failed", self._failed, item)
        self._notify()

    def _decide(self, download, suggested, item) -> bool:
        dest = unique_path(paths.download_dir(), sanitize_filename(suggested))
        download.set_allow_overwrite(False)
        download.set_destination(GLib.filename_to_uri(dest, None))
        item.dest = dest
        item.filename = os.path.basename(dest)
        self._notify()
        return True

    def _progress(self, download, _pspec, item) -> None:
        item.progress = download.get_estimated_progress()
        self._notify()

    def _finished(self, _download, item) -> None:
        if item.state == "downloading":
            item.state = "finished"
            item.progress = 1.0
        self._notify()

    def _failed(self, _download, error, item) -> None:
        item.state = "cancelled" if item.cancelled else "failed"
        item.error = "" if item.cancelled else (error.message if error else "unknown error")
        self._notify()

    def cancel(self, item: DownloadItem) -> None:
        if item.state == "downloading":
            item.cancelled = True
            item.download.cancel()

    def cancel_all(self) -> None:
        for item in self.items:
            self.cancel(item)

    def clear_finished(self) -> None:
        self.items = [i for i in self.items if i.state == "downloading"]
        self._notify()
