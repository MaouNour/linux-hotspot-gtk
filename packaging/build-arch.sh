#!/bin/bash
# Build the Arch package. Run on Arch (or in a container) as a NORMAL user —
# makepkg refuses to run as root. In CI/containers use packaging/build.sh or
# the workflow, which create a build user. Needs: base-devel desktop-file-utils
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
VERSION=$(cat "$ROOT/VERSION")
TARBALL="$ROOT/dist/hotspot-toggle-$VERSION.tar.gz"
[[ -f $TARBALL ]] || make -C "$ROOT" dist

WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
cp "$TARBALL" "$WORK/"
sed "s/@VERSION@/$VERSION/g" "$ROOT/packaging/arch/PKGBUILD" > "$WORK/PKGBUILD"
cd "$WORK"
# -s installs missing deps via sudo, which also proves the package names resolve.
makepkg -f -s --noconfirm
mkdir -p "$ROOT/dist"
cp "$WORK"/hotspot-toggle-*.pkg.tar.zst "$ROOT/dist/"
echo "==> $(ls "$ROOT"/dist/hotspot-toggle-*.pkg.tar.zst)"
