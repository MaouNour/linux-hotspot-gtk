#!/bin/bash
# Build the .rpm. Run on Fedora (or in a container) with:
#   dnf install -y rpm-build make desktop-file-utils
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
VERSION=$(cat "$ROOT/VERSION")
TARBALL="$ROOT/dist/hotspot-toggle-$VERSION.tar.gz"
[[ -f $TARBALL ]] || make -C "$ROOT" dist

TOP=$(mktemp -d); trap 'rm -rf "$TOP"' EXIT
mkdir -p "$TOP"/{SOURCES,SPECS}
cp "$TARBALL" "$TOP/SOURCES/"
sed -e "s/@VERSION@/$VERSION/g" -e "s/@RPMDATE@/$(LC_ALL=C date '+%a %b %d %Y')/" \
    "$ROOT/packaging/rpm/hotspot-toggle.spec" > "$TOP/SPECS/hotspot-toggle.spec"

# RPMBUILD_ARGS lets you pass e.g. --nodeps when building on a non-RPM host
# shellcheck disable=SC2086  # intentional word splitting of extra args
rpmbuild -bb ${RPMBUILD_ARGS:-} --define "_topdir $TOP" "$TOP/SPECS/hotspot-toggle.spec"
mkdir -p "$ROOT/dist"
cp "$TOP"/RPMS/noarch/hotspot-toggle-*.rpm "$ROOT/dist/"
echo "==> $(ls "$ROOT"/dist/hotspot-toggle-*.rpm)"
