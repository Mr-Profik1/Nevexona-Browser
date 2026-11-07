"""Address-bar input handling and search engines. Pure Python."""
from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlencode

START_URL = "nevex:start"

# key -> (display name, action URL, query parameter)
SEARCH_ENGINES = {
    "yandex": ("Yandex", "https://yandex.ru/search/", "text"),
    "duckduckgo": ("DuckDuckGo", "https://duckduckgo.com/", "q"),
    "google": ("Google", "https://www.google.com/search", "q"),
    "bing": ("Bing", "https://www.bing.com/search", "q"),
}
DEFAULT_ENGINE = "yandex"

_ALLOWED_SCHEMES = ("http", "https", "file")
_SCHEME = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*)://")
_HOST = re.compile(
    r"^(?:[\w\-]+\.)+[^\W\d_]{2,}(?::\d{1,5})?(?:[/?#].*)?$", re.UNICODE
)
_LOCAL = re.compile(
    r"^(?:localhost|\d{1,3}(?:\.\d{1,3}){3}|\[[0-9a-fA-F:]+\])(?::\d{1,5})?(?:[/?#].*)?$"
)


def search_url(query: str, engine: str = DEFAULT_ENGINE) -> str:
    _, action, param = SEARCH_ENGINES.get(engine, SEARCH_ENGINES[DEFAULT_ENGINE])
    return action + "?" + urlencode({param: query})


def resolve_input(text: str, engine: str = DEFAULT_ENGINE) -> str:
    """Turn what the user typed into a URL to load ('' if nothing typed).

    javascript:, data: and other non-web schemes are never loaded from the
    address bar; they are treated as a search query instead.
    """
    t = (text or "").strip()
    if not t:
        return ""
    if t.lower() == START_URL:
        return START_URL
    if t.lower() == "about:blank":
        return "about:blank"
    if not re.search(r"\s", t):
        m = _SCHEME.match(t)
        if m:
            if m.group(1).lower() in _ALLOWED_SCHEMES:
                return t
            return search_url(t, engine)
        if _LOCAL.match(t):
            return "http://" + t
        if _HOST.match(t):
            return "https://" + t
    if t[0] in "/~":
        p = os.path.expanduser(t)
        if os.path.exists(p):
            return Path(os.path.abspath(p)).as_uri()
    return search_url(t, engine)


def display_url(uri: str | None) -> str:
    """What to show in the address bar for a page URI."""
    if not uri or uri.startswith("about:blank") or uri == START_URL:
        return ""
    return uri


def is_web_url(uri: str | None) -> bool:
    return bool(uri) and uri.split(":", 1)[0].lower() in ("http", "https")
