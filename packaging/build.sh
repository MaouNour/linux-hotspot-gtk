#!/bin/bash
# Build packages locally in clean containers (podman or docker):
#
#   packaging/build.sh              # everything: deb rpm arch appimage
#   packaging/build.sh deb rpm      # just these
#
# Results land in dist/. Needs on the host: make, git, tar, and podman|docker.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

ENGINE=${CONTAINER_ENGINE:-$(command -v podman || command -v docker || true)}
[[ -n $ENGINE ]] || { echo "podman or docker is required (or run packaging/build-<fmt>.sh natively)" >&2; exit 1; }

declare -A IMAGE=( [deb]=ubuntu:24.04 [appimage]=ubuntu:24.04 [rpm]=fedora:latest [arch]=archlinux:latest )
formats=("$@")
[[ ${#formats[@]} -gt 0 ]] || formats=(deb rpm arch appimage)

VERSION=$(cat VERSION)
[[ -f dist/hotspot-toggle-$VERSION.tar.gz ]] || make dist

for fmt in "${formats[@]}"; do
    [[ -n ${IMAGE[$fmt]:-} ]] || { echo "unknown format: $fmt (deb|rpm|arch|appimage)" >&2; exit 2; }
    echo "=================== $fmt (${IMAGE[$fmt]}) ==================="
    "$ENGINE" run --rm -v "$ROOT":/src:Z -w /src \
        -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
        "${IMAGE[$fmt]}" bash packaging/container-build.sh "$fmt"
done

echo
ls -1 dist
