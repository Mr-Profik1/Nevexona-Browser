#!/usr/bin/env bash
# Install NEVEX AI from this source checkout.
#   ./install.sh               per-user install into ~/.local  (no root, except apt for dependencies)
#   sudo ./install.sh --system system-wide install into /usr
#   ./install.sh --no-deps     skip the apt dependency step
#   ./install.sh --uninstall   remove what this script installed
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE=user; DEPS=1; UNINSTALL=0
for a in "$@"; do
  case "$a" in
    --system) MODE=system ;;
    --no-deps) DEPS=0 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "Unknown option: $a" >&2; exit 2 ;;
  esac
done

if [ "$MODE" = system ]; then
  [ "$(id -u)" -eq 0 ] || { echo "--system needs root: sudo ./install.sh --system" >&2; exit 1; }
  LIB=/usr/lib/nevex-browser; BIN=/usr/bin; SHARE=/usr/share
else
  LIB="$HOME/.local/lib/nevex-browser"; BIN="$HOME/.local/bin"; SHARE="${XDG_DATA_HOME:-$HOME/.local/share}"
fi

refresh_caches() {
  command -v update-desktop-database >/dev/null && update-desktop-database "$SHARE/applications" 2>/dev/null || true
  command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$SHARE/icons/hicolor" 2>/dev/null || true
}

if [ "$UNINSTALL" -eq 1 ]; then
  rm -rf "$LIB"
  rm -f "$BIN/nevex-browser" "$SHARE/applications/nevex-browser.desktop" "$SHARE/icons/hicolor/scalable/apps/nevex-browser.svg"
  for s in 16 32 48 64 128 256; do rm -f "$SHARE/icons/hicolor/${s}x${s}/apps/nevex-browser.png"; done
  refresh_caches
  echo "NEVEX AI removed. Your settings remain in ~/.config/nevex-browser (delete it if you want)."
  exit 0
fi

if [ "$DEPS" -eq 1 ]; then
  if ! command -v apt-get >/dev/null; then
    echo "apt-get not found. Install the packages in packaging/system-dependencies.txt yourself, then run with --no-deps." >&2
    exit 1
  fi
  if apt-cache show gir1.2-webkit2-4.1 >/dev/null 2>&1; then WK=gir1.2-webkit2-4.1; else WK=gir1.2-webkit2-4.0; fi
  MISSING=()
  for p in python3 python3-gi gir1.2-gtk-3.0 "$WK" librsvg2-common; do
    dpkg -s "$p" >/dev/null 2>&1 || MISSING+=("$p")
  done
  if [ "${#MISSING[@]}" -gt 0 ]; then
    echo "Installing system packages: ${MISSING[*]}"
    if [ "$(id -u)" -eq 0 ]; then apt-get install -y "${MISSING[@]}"; else sudo apt-get install -y "${MISSING[@]}"; fi
  fi
fi

install -d "$LIB" "$BIN" "$SHARE/applications" "$SHARE/icons/hicolor/scalable/apps"
rm -rf "$LIB/nevex"
cp -r "$SRC/nevex" "$LIB/nevex"
find "$LIB" -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
cat > "$BIN/nevex-browser" <<LAUNCH
#!/usr/bin/python3
import sys
sys.path.insert(0, "$LIB")
from nevex.app import main
sys.exit(main())
LAUNCH
chmod 755 "$BIN/nevex-browser"
install -m644 "$SRC/data/icons/nevex-browser.svg" "$SHARE/icons/hicolor/scalable/apps/nevex-browser.svg"
for s in 16 32 48 64 128 256; do
  install -Dm644 "$SRC/data/icons/png/nevex-browser-$s.png" "$SHARE/icons/hicolor/${s}x${s}/apps/nevex-browser.png"
done
sed "s|^Exec=nevex-browser|Exec=$BIN/nevex-browser|" "$SRC/data/nevex-browser.desktop" > "$SHARE/applications/nevex-browser.desktop"
chmod 644 "$SHARE/applications/nevex-browser.desktop"
/usr/bin/python3 -m compileall -q "$LIB" || true   # precompile: faster start on slow CPUs
refresh_caches

echo "NEVEX AI installed ($MODE). Start it from the menu (Internet > NEVEX AI) or run: $BIN/nevex-browser"
case ":$PATH:" in *":$BIN:"*) ;; *) [ "$MODE" = user ] && echo "Note: $BIN is not in your PATH yet; log out and in again or use the full path." ;; esac
