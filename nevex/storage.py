"""Persistent state: settings, bookmarks, history, session, API key. Pure Python."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time

from . import paths


def write_json_atomic(path: str, data, mode: int | None = None, sync: bool = True) -> None:
    folder = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            if sync:
                os.fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (ValueError, OSError):
        try:  # keep the unreadable file for inspection, start fresh
            os.replace(path, path + ".bad")
        except OSError:
            pass
        return default


DEFAULT_SETTINGS = {
    "homepage": "nevex:start",
    "search_engine": "yandex",
    "restore_session": True,
    "reduced_memory": False,
    "hibernate_minutes": 5,
    "ai_enabled": False,
    "ai_endpoint": "",
    "ai_model": "",
}


class Settings:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(paths.config_dir(), "settings.json")
        self._d = dict(DEFAULT_SETTINGS)
        loaded = read_json(self.path, {})
        if isinstance(loaded, dict):
            for k, default in DEFAULT_SETTINGS.items():
                v = loaded.get(k)
                if isinstance(v, type(default)):
                    self._d[k] = v

    def get(self, key: str):
        return self._d[key]

    def set(self, key: str, value) -> None:
        if key not in DEFAULT_SETTINGS:
            raise KeyError(key)
        if not isinstance(value, type(DEFAULT_SETTINGS[key])):
            raise TypeError("%s must be %s" % (key, type(DEFAULT_SETTINGS[key]).__name__))
        self._d[key] = value

    def save(self) -> None:
        write_json_atomic(self.path, self._d)


class ApiKeyStore:
    """API key kept in its own file (mode 0600). NEVEX_AI_API_KEY overrides it.

    The key is stored in plain text: there is no portable keyring that does not
    add a heavy dependency. Anyone who can read your home directory can read it.
    """

    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(paths.config_dir(), "ai_key.json")

    def get(self) -> str:
        env = os.environ.get("NEVEX_AI_API_KEY")
        if env:
            return env.strip()
        data = read_json(self.path, {})
        key = data.get("api_key") if isinstance(data, dict) else ""
        return key if isinstance(key, str) else ""

    def set(self, key: str) -> None:
        key = (key or "").strip()
        if not key:
            try:
                os.unlink(self.path)
            except FileNotFoundError:
                pass
            return
        write_json_atomic(self.path, {"api_key": key}, mode=0o600)


class Bookmarks:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(paths.config_dir(), "bookmarks.json")
        data = read_json(self.path, [])
        self._items = [
            {"title": str(i.get("title", "")), "url": i["url"], "added": i.get("added", 0)}
            for i in (data if isinstance(data, list) else [])
            if isinstance(i, dict) and isinstance(i.get("url"), str)
        ]

    def all(self) -> list:
        return list(self._items)

    def contains(self, url: str) -> bool:
        return any(i["url"] == url for i in self._items)

    def add(self, url: str, title: str = "") -> bool:
        if not url or self.contains(url):
            return False
        self._items.insert(0, {"title": title or url, "url": url, "added": int(time.time())})
        self.save()
        return True

    def remove(self, url: str) -> bool:
        n = len(self._items)
        self._items = [i for i in self._items if i["url"] != url]
        if len(self._items) != n:
            self.save()
            return True
        return False

    def toggle(self, url: str, title: str = "") -> bool:
        """Add or remove; returns True if the page is bookmarked afterwards."""
        if self.contains(url):
            self.remove(url)
            return False
        self.add(url, title)
        return True

    def search(self, query: str = "") -> list:
        q = query.lower().strip()
        return [i for i in self._items if not q or q in i["url"].lower() or q in i["title"].lower()]

    def save(self) -> None:
        write_json_atomic(self.path, self._items)


class History:
    def __init__(self, path: str | None = None, max_rows: int = 5000):
        self.path = path or os.path.join(paths.data_dir(), "history.db")
        self.max_rows = max_rows
        self._adds = 0
        self.db = sqlite3.connect(self.path)
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS history ("
            "url TEXT PRIMARY KEY, title TEXT, visits INTEGER NOT NULL DEFAULT 1, "
            "last_visit INTEGER NOT NULL)"
        )
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_last ON history(last_visit)")
        self.db.commit()

    def add(self, url: str, title: str = "") -> None:
        now = int(time.time())
        cur = self.db.execute(
            "UPDATE history SET visits = visits + 1, last_visit = ?, "
            "title = CASE WHEN ? != '' THEN ? ELSE title END WHERE url = ?",
            (now, title, title, url),
        )
        if cur.rowcount == 0:
            self.db.execute(
                "INSERT INTO history (url, title, visits, last_visit) VALUES (?, ?, 1, ?)",
                (url, title or url, now),
            )
        self.db.commit()
        self._adds += 1
        if self._adds % 200 == 0:
            self.db.execute(
                "DELETE FROM history WHERE url NOT IN "
                "(SELECT url FROM history ORDER BY last_visit DESC LIMIT ?)",
                (self.max_rows,),
            )
            self.db.commit()

    def recent(self, query: str = "", limit: int = 300) -> list:
        like = "%" + query.replace("%", "").replace("_", "") + "%"
        rows = self.db.execute(
            "SELECT title, url, last_visit FROM history "
            "WHERE url LIKE ? OR title LIKE ? ORDER BY last_visit DESC LIMIT ?",
            (like, like, limit),
        ).fetchall()
        return [{"title": r[0] or r[1], "url": r[1], "last_visit": r[2]} for r in rows]

    def delete(self, url: str) -> None:
        self.db.execute("DELETE FROM history WHERE url = ?", (url,))
        self.db.commit()

    def clear(self) -> None:
        self.db.execute("DELETE FROM history")
        self.db.commit()

    def close(self) -> None:
        try:
            self.db.close()
        except sqlite3.Error:
            pass


class SessionStore:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(paths.config_dir(), "session.json")

    def save(self, tabs: list, active: int) -> None:
        write_json_atomic(self.path, {"tabs": tabs, "active": active}, sync=False)

    def load(self):
        """Return (tabs, active); tabs is a list of {'url', 'title'}."""
        data = read_json(self.path, {})
        if not isinstance(data, dict):
            return [], 0
        tabs = [
            {"url": t["url"], "title": str(t.get("title", ""))}
            for t in data.get("tabs", [])
            if isinstance(t, dict) and isinstance(t.get("url"), str) and t["url"]
        ]
        active = data.get("active", 0)
        if not isinstance(active, int) or not 0 <= active < len(tabs):
            active = 0
        return tabs, active
