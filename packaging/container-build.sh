#!/bin/bash
# Runs INSIDE a clean build environment, as root: installs the build tools for
# one package format and builds it. Used by packaging/build.sh (local, via
# podman/docker) and by the GitHub workflows, so both do exactly the same thing.
#   packaging/container-build.sh deb|rpm|arch|appimage
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
fmt=${1:?usage: container-build.sh deb|rpm|arch|appimage}

case "$fmt" in
    deb)
        export DEBIAN_FRONTEND=noninteractive
        apt-get update
        apt-get install -y --no-install-recommends build-essential debhelper dpkg-dev \
            desktop-file-utils ca-certificates git
        packaging/build-deb.sh ;;
    appimage)
        export DEBIAN_FRONTEND=noninteractive
        apt-get update
        apt-get install -y --no-install-recommends build-essential libglib2.0-bin \
            desktop-file-utils ca-certificates curl git file
        packaging/build-appimage.sh ;;
    rpm)
        dnf install -y rpm-build make desktop-file-utils git tar gzip
        packaging/build-rpm.sh ;;
    arch)
        pacman -Syu --noconfirm --needed base-devel sudo git python desktop-file-utils
        # makepkg refuses to run as root: build as a throwaway user in a copy.
        id builder >/dev/null 2>&1 || useradd -m builder
        echo 'builder ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/builder
        rm -rf /home/builder/src
        cp -a "$ROOT" /home/builder/src
        chown -R builder /home/builder/src
        su builder -c 'cd /home/builder/src && packaging/build-arch.sh'
        mkdir -p dist
        cp /home/builder/src/dist/*.pkg.tar.zst dist/ ;;
    *) echo "unknown format: $fmt" >&2; exit 2 ;;
esac

# Hand build output back to the invoking user (containers run as root).
if [[ -n "${HOST_UID:-}" ]]; then
    chown -R "$HOST_UID:${HOST_GID:-$HOST_UID}" dist build 2>/dev/null || true
fi
