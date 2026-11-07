"""Import GTK 3 and WebKit2GTK, preferring API 4.1 (Mint 21/22) over 4.0 (Mint 20)."""
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

WebKit2 = None
WEBKIT_API = None
for _v in ("4.1", "4.0"):
    try:
        gi.require_version("WebKit2", _v)
        from gi.repository import WebKit2  # noqa: E402,F811
        WEBKIT_API = _v
        break
    except (ValueError, ImportError):
        continue

if WebKit2 is None:
    raise ImportError(
        "WebKit2GTK typelib not found. Install it with: "
        "sudo apt install gir1.2-webkit2-4.1 (or gir1.2-webkit2-4.0 on Mint 20)"
    )
