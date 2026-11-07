"""Dark charcoal + orange accent theme. No animations."""
from .webkit_compat import Gtk, Gdk

CSS = b"""
window, .nx-root { background-color: #1e1f22; color: #e6e6e6; }
.nx-toolbar { background-color: #26272b; padding: 4px 6px; border-bottom: 1px solid #1a1b1d; }
.nx-toolbar button, .nx-sidebar button, .nx-tabbtn {
  background-image: none; background-color: transparent; border: 1px solid transparent;
  border-radius: 6px; padding: 2px 6px; min-height: 24px; min-width: 24px; box-shadow: none;
  color: #e6e6e6; }
.nx-toolbar button:hover, .nx-sidebar button:hover, .nx-tabbtn:hover { background-color: #3a3c41; }
.nx-toolbar button:disabled { color: #6b6d72; }
.nx-toolbar button.nx-on { color: #ff7a1a; }
entry.nx-url, .nx-sidebar entry, .nx-sidebar textview text {
  background-image: none; background-color: #1e1f22; color: #e6e6e6;
  border: 1px solid #3a3c41; border-radius: 8px; padding: 3px 10px; min-height: 24px; box-shadow: none; }
entry.nx-url:focus, .nx-sidebar entry:focus { border-color: #ff7a1a; }
progressbar.nx-progress trough { min-height: 2px; background-color: #26272b; border: none; }
progressbar.nx-progress progress { min-height: 2px; background-color: #ff7a1a; border: none; }
notebook > header { background-color: #26272b; border: none; padding: 0; }
notebook > header > tabs > tab {
  background-color: #26272b; border: none; border-radius: 0; padding: 3px 6px; min-height: 22px; color: #a8aaaf; }
notebook > header > tabs > tab:checked { background-color: #1e1f22; color: #e6e6e6; border-bottom: 2px solid #ff7a1a; }
notebook > header > tabs > tab:hover { background-color: #303236; }
.nx-sidebar { background-color: #26272b; border-left: 1px solid #1a1b1d; padding: 6px; }
.nx-sidebar label.nx-title { color: #ff7a1a; font-weight: bold; }
.nx-error { color: #ff6b6b; }
.nx-dim { color: #8d8f94; }
button.nx-accent { background-color: #ff7a1a; color: #1e1f22; font-weight: bold; }
button.nx-accent:hover { background-color: #ff9a4d; }
"""


def apply_theme() -> None:
    settings = Gtk.Settings.get_default()
    settings.set_property("gtk-application-prefer-dark-theme", True)
    settings.set_property("gtk-enable-animations", False)
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
