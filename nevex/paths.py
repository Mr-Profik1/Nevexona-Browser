"""Filesystem locations. Pure Python (no GTK) so it can be tested anywhere.

Set NEVEX_PROFILE=/some/dir to keep config, data and cache in one directory
(used by --profile, tests and the memory benchmark).
"""
from __future__ import annotations

import os
import re

DIRNAME = "nevex-browser"


def _ensure(path: str) -> str:
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def _xdg(env: str, fallback: str) -> str:
    return os.environ.get(env) or os.path.expanduser(fallback)


def config_dir() -> str:
    root = os.environ.get("NEVEX_PROFILE")
    if root:
        return _ensure(os.path.join(root, "config"))
    return _ensure(os.path.join(_xdg("XDG_CONFIG_HOME", "~/.config"), DIRNAME))


def data_dir() -> str:
    root = os.environ.get("NEVEX_PROFILE")
    if root:
        return _ensure(os.path.join(root, "data"))
    return _ensure(os.path.join(_xdg("XDG_DATA_HOME", "~/.local/share"), DIRNAME))


def cache_dir() -> str:
    root = os.environ.get("NEVEX_PROFILE")
    if root:
        return _ensure(os.path.join(root, "cache"))
    return _ensure(os.path.join(_xdg("XDG_CACHE_HOME", "~/.cache"), DIRNAME))


def _user_dirs_download() -> str | None:
    cfg = os.path.join(_xdg("XDG_CONFIG_HOME", "~/.config"), "user-dirs.dirs")
    try:
        with open(cfg, encoding="utf-8") as f:
            for line in f:
                m = re.match(r'\s*XDG_DOWNLOAD_DIR\s*=\s*"?([^"\n]+)"?', line)
                if m:
                    return m.group(1).replace("$HOME", os.path.expanduser("~"))
    except OSError:
        pass
    return None


def download_dir() -> str:
    override = os.environ.get("NEVEX_DOWNLOAD_DIR")
    path = override or _user_dirs_download() or os.path.expanduser("~/Downloads")
    os.makedirs(path, exist_ok=True)
    return path
