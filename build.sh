#!/usr/bin/env bash
# Build dist/nevex-browser_<version>_all.deb  (needs dpkg-deb; run ./build.sh)
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SRC"
VERSION="$(python3 -c 'import re;print(re.search(r"__version__ = \"([^\"]+)\"",open("nevex/__init__.py").read()).group(1))')"
PKG="nevex-browser_${VERSION}_all"
STAGE="build/$PKG"
rm -rf "$STAGE"
install -d "$STAGE/DEBIAN" "$STAGE/usr/lib/nevex-browser" "$STAGE/usr/bin" \
  "$STAGE/usr/share/applications" "$STAGE/usr/share/icons/hicolor/scalable/apps" "$STAGE/usr/share/doc/nevex-browser"
cp -r nevex "$STAGE/usr/lib/nevex-browser/nevex"
find "$STAGE" -name __pycache__ -prune -exec rm -rf {} +
cat > "$STAGE/usr/bin/nevex-browser" <<'LAUNCH'
#!/usr/bin/python3
import sys
sys.path.insert(0, "/usr/lib/nevex-browser")
from nevex.app import main
sys.exit(main())
LAUNCH
chmod 755 "$STAGE/usr/bin/nevex-browser"
install -m644 data/nevex-browser.desktop "$STAGE/usr/share/applications/nevex-browser.desktop"
install -m644 data/icons/nevex-browser.svg "$STAGE/usr/share/icons/hicolor/scalable/apps/nevex-browser.svg"
for s in 16 32 48 64 128 256; do
  install -Dm644 "data/icons/png/nevex-browser-$s.png" "$STAGE/usr/share/icons/hicolor/${s}x${s}/apps/nevex-browser.png"
done
install -m644 LICENSE "$STAGE/usr/share/doc/nevex-browser/copyright"
SIZE=$(du -sk "$STAGE/usr" | cut -f1)
cat > "$STAGE/DEBIAN/control" <<CONTROL
Package: nevex-browser
Version: $VERSION
Section: web
Priority: optional
Architecture: all
Installed-Size: $SIZE
Depends: python3 (>= 3.8), python3-gi, gir1.2-gtk-3.0, gir1.2-webkit2-4.1 | gir1.2-webkit2-4.0, librsvg2-common
Maintainer: NEVEX AI <noreply@users.noreply.github.com>
Description: NEVEX AI - lightweight web browser with an optional AI assistant
 Tabs, bookmarks, history, downloads and private windows on top of WebKitGTK,
 designed for low-memory computers. The AI sidebar is off by default and talks
 only to an OpenAI-compatible endpoint that you configure.
CONTROL
cat > "$STAGE/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
python3 -m compileall -q /usr/lib/nevex-browser >/dev/null 2>&1 || true
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
exit 0
POST
cat > "$STAGE/DEBIAN/prerm" <<'PRE'
#!/bin/sh
set -e
find /usr/lib/nevex-browser -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
exit 0
PRE
cat > "$STAGE/DEBIAN/postrm" <<'POSTRM'
#!/bin/sh
set -e
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
exit 0
POSTRM
chmod 755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm" "$STAGE/DEBIAN/postrm"
( cd "$STAGE" && find usr -type f -exec md5sum {} + > DEBIAN/md5sums )
mkdir -p dist
dpkg-deb --root-owner-group --build "$STAGE" "dist/$PKG.deb" >/dev/null
echo "Built dist/$PKG.deb"
dpkg-deb --info "dist/$PKG.deb" | sed -n '1,12p'
