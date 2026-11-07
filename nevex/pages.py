"""HTML for the built-in start page and error pages. Pure Python."""
from __future__ import annotations

import html

from .urlutil import SEARCH_ENGINES, DEFAULT_ENGINE, is_web_url

_CSS = """
*{box-sizing:border-box}
body{margin:0;background:#1e1f22;color:#e6e6e6;font:15px/1.5 system-ui,"Noto Sans","DejaVu Sans",sans-serif;
display:flex;flex-direction:column;align-items:center;padding:12vh 20px 40px}
h1{margin:0 0 4px;font-size:34px;letter-spacing:3px;font-weight:700}
h1 b{color:#ff7a1a}
.sub{color:#8d8f94;margin:0 0 28px}
form{width:100%;max-width:560px;display:flex;gap:8px}
input[type=text]{flex:1;padding:11px 14px;border-radius:8px;border:1px solid #3a3c41;background:#2a2b2f;color:#e6e6e6;font-size:15px;outline:none}
input[type=text]:focus{border-color:#ff7a1a}
button{padding:0 18px;border-radius:8px;border:0;background:#ff7a1a;color:#1e1f22;font-weight:600;font-size:15px;cursor:pointer}
.links{margin-top:34px;width:100%;max-width:560px;display:flex;flex-wrap:wrap;gap:8px}
.links a{padding:7px 12px;border-radius:6px;background:#2a2b2f;color:#e6e6e6;text-decoration:none;max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.links a:hover{background:#34363b;color:#ff9a4d}
.note{color:#ff9a4d;margin-top:20px}
.err{max-width:560px}
.err h2{color:#ff9a4d;margin:0 0 8px}
.err code{background:#2a2b2f;padding:2px 6px;border-radius:4px;word-break:break-all}
.err a.btn{display:inline-block;margin-top:16px;padding:9px 18px;border-radius:8px;background:#ff7a1a;color:#1e1f22;text-decoration:none;font-weight:600}
"""

_CSP = ("default-src 'none'; style-src 'unsafe-inline'; form-action https:")


def _head(title: str) -> str:
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="%s">'
        "<title>%s</title><style>%s</style></head><body>" % (_CSP, html.escape(title), _CSS)
    )


def start_page_html(engine: str = DEFAULT_ENGINE, bookmarks=(), private: bool = False) -> str:
    name, action, param = SEARCH_ENGINES.get(engine, SEARCH_ENGINES[DEFAULT_ENGINE])
    links = "".join(
        '<a href="%s" rel="noopener" title="%s">%s</a>'
        % (html.escape(b["url"], quote=True), html.escape(b["url"], quote=True),
           html.escape(b.get("title") or b["url"]))
        for b in list(bookmarks)[:12]
        if is_web_url(b.get("url"))
    )
    note = (
        '<p class="note">Private window: history and cookies are not kept after you close it.</p>'
        if private else ""
    )
    return (
        _head("NEVEX AI")
        + '<h1>NEVEX <b>AI</b></h1><p class="sub">Search with %s</p>' % html.escape(name)
        + '<form action="%s" method="get"><input type="text" name="%s" autofocus '
          'autocomplete="off" placeholder="Search or enter address"><button type="submit">Search</button></form>'
          % (html.escape(action, quote=True), html.escape(param, quote=True))
        + ('<div class="links">%s</div>' % links if links else "")
        + note + "</body></html>"
    )


def error_page_html(url: str, message: str, code=None) -> str:
    retry = (
        '<a class="btn" href="%s">Try again</a>' % html.escape(url, quote=True)
        if is_web_url(url) else ""
    )
    code_txt = " (error %s)" % html.escape(str(code)) if code is not None else ""
    return (
        _head("Cannot open page")
        + '<div class="err"><h2>This page could not be loaded</h2>'
        + "<p><code>%s</code></p><p>%s%s</p>%s</div></body></html>"
        % (html.escape(url), html.escape(message or "Unknown error"), code_txt, retry)
    )
