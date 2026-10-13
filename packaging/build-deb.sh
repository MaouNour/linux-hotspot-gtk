#!/bin/bash
# Build the .deb. Run on Debian/Ubuntu (or in a container) with:
#   apt-get install -y build-essential debhelper dpkg-dev desktop-file-utils
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
VERSION=$(cat "$ROOT/VERSION")
TARBALL="$ROOT/dist/hotspot-toggle-$VERSION.tar.gz"
[[ -f $TARBALL ]] || make -C "$ROOT" dist

WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
tar -xzf "$TARBALL" -C "$WORK"
cd "$WORK/hotspot-toggle-$VERSION"

mkdir debian
cp -r packaging/debian/control packaging/debian/rules packaging/debian/copyright \
      packaging/debian/source debian/
sed -e "s/@VERSION@/$VERSION/g" -e "s/@DEBDATE@/$(LC_ALL=C date -R)/" \
    packaging/debian/changelog.in > debian/changelog

dpkg-buildpackage -us -uc -b
mkdir -p "$ROOT/dist"
cp "$WORK"/hotspot-toggle_"${VERSION}"_all.deb "$ROOT/dist/"
echo "==> dist/hotspot-toggle_${VERSION}_all.deb"
