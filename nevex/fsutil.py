"""Small filesystem helpers for downloads. Pure Python."""
from __future__ import annotations

import os
import re

_BAD = re.compile(r'[\x00-\x1f<>:"/\\|?*]')


def sanitize_filename(name: str, default: str = "download") -> str:
    """Return a safe single path component for a server-suggested filename."""
    name = os.path.basename((name or "").replace("\\", "/")).strip().strip(".")
    name = _BAD.sub("_", name)
    if not name:
        name = default
    if len(name.encode("utf-8")) > 200:
        stem, ext = os.path.splitext(name)
        stem = stem.encode("utf-8")[:150].decode("utf-8", "ignore")
        name = stem + ext[:20]
    return name


def unique_path(folder: str, name: str) -> str:
    """Return folder/name, or folder/name (1).ext etc. if it already exists."""
    stem, ext = os.path.splitext(name)
    candidate = os.path.join(folder, name)
    n = 0
    while os.path.exists(candidate) or os.path.exists(candidate + ".part"):
        n += 1
        candidate = os.path.join(folder, "%s (%d)%s" % (stem, n, ext))
    return candidate
