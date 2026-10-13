#!/bin/bash
# Build the AppImage. Needs: make, tar, glib-compile-schemas (libglib2.0-bin /
# glib2), curl, and network access to download appimagetool (cached in build/).
#
# Honest scope: this AppImage bundles the app, the CLI and create_ap, but NOT
# GTK4/libadwaita/Python (bundling the GNOME stack is impractical and
# the hotspot needs host hostapd/dnsmasq/systemd/polkit anyway). Instead its
# AppRun installs whatever the host is missing, once, with one password prompt.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
VERSION=$(cat "$ROOT/VERSION")
ARCH=${ARCH:-$(uname -m)}
TARBALL="$ROOT/dist/hotspot-toggle-$VERSION.tar.gz"
[[ -f $TARBALL ]] || make -C "$ROOT" dist

WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
tar -xzf "$TARBALL" -C "$WORK"
SRC="$WORK/hotspot-toggle-$VERSION"
APPDIR="$WORK/AppDir"
APP_ID=io.github.local.hotspot-toggle

make -C "$SRC" install DESTDIR="$APPDIR" PREFIX=/usr BUNDLE_CREATE_AP=1

# System-level pieces don't belong inside the AppImage; they ship as the
# first-run payload instead (see packaging/appimage/AppRun).
rm -rf "${APPDIR:?}/etc" "${APPDIR:?}/usr/share/polkit-1" "${APPDIR:?}/usr/share/doc" \
       "${APPDIR:?}/usr/share/man" "${APPDIR:?}/usr/share/bash-completion"
SYSDIR="$APPDIR/usr/share/hotspot-toggle/system"
mkdir -p "$SYSDIR"
cp "$SRC/bin/gnome-hotspot-helper" "$SRC/polkit/49-hotspot-toggle.rules" \
   "$SRC/polkit/local.hotspot-toggle.policy" "$SRC/scripts/deps.sh" \
   "$SRC/packaging/appimage/setup.sh" "$SYSDIR/"
cp "$SRC/vendor/create_ap/create_ap" "$SYSDIR/create_ap"
chmod 755 "$SYSDIR/setup.sh" "$SYSDIR/gnome-hotspot-helper" "$SYSDIR/create_ap"

glib-compile-schemas "$APPDIR/usr/share/glib-2.0/schemas"
install -m755 "$SRC/packaging/appimage/AppRun" "$APPDIR/AppRun"
cp "$SRC/data/$APP_ID.desktop" "$APPDIR/$APP_ID.desktop"
cp "$SRC/data/$APP_ID.svg" "$APPDIR/$APP_ID.svg"

mkdir -p "$ROOT/build" "$ROOT/dist"
TOOL="$ROOT/build/appimagetool-$ARCH.AppImage"
if [[ ! -x $TOOL ]]; then
    curl -fsSL -o "$TOOL" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage"
    chmod +x "$TOOL"
fi

OUT="$ROOT/dist/Hotspot-Toggle-$VERSION-$ARCH.AppImage"
# APPIMAGE_EXTRACT_AND_RUN avoids needing FUSE (CI containers don't have it).
ARCH=$ARCH APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" "$APPDIR" "$OUT"
echo "==> $OUT"
