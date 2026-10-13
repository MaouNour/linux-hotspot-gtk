#!/bin/bash
# install.sh — one-step installer for Hotspot Toggle (GUI + CLI).
#
#   ./install.sh                 install dependencies, create_ap and the app
#   ./install.sh --no-deps       skip the distro package step
#   ./install.sh --deps-only     only install distro dependencies
#   ./install.sh --uninstall     remove the app (leaves create_ap alone)
#   PREFIX=/usr ./install.sh     choose the install prefix (default /usr/local)
#
# Supports Fedora/RHEL-likes (dnf), Arch-likes (pacman) and Debian/Ubuntu-likes (apt).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${PREFIX:-/usr/local}"
# shellcheck source=scripts/deps.sh
source "$SCRIPT_DIR/scripts/deps.sh"

DO_DEPS=1 DEPS_ONLY=0 UNINSTALL=0
for arg in "$@"; do
    case "$arg" in
        --no-deps)   DO_DEPS=0 ;;
        --deps-only) DEPS_ONLY=1 ;;
        --uninstall) UNINSTALL=1 ;;
        -h|--help)   sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $arg (see --help)" >&2; exit 2 ;;
    esac
done

if [[ $UNINSTALL -eq 1 ]]; then
    hs_sudo make -C "$SCRIPT_DIR" uninstall PREFIX="$PREFIX"
    echo "==> Uninstalled. (create_ap and distro packages were left in place.)"
    exit 0
fi

if [[ $DO_DEPS -eq 1 ]]; then
    hs_install_deps
fi
[[ $DEPS_ONLY -eq 1 ]] && exit 0

echo "==> Checking GTK4 + libadwaita + PyGObject..."
if ! hs_gui_stack_ok; then
    echo "Missing PyGObject/GTK4/libadwaita (>= 1.4). Re-run without --no-deps," >&2
    echo "or see README.md for your distro's package names." >&2
    exit 1
fi

echo "==> Checking create_ap..."
if command -v create_ap >/dev/null 2>&1; then
    echo "    found: $(command -v create_ap)"
elif [[ -x /usr/local/lib/hotspot-toggle/create_ap || -x /usr/lib/hotspot-toggle/create_ap ]]; then
    echo "    found bundled copy"
else
    if ! command -v git >/dev/null 2>&1 || ! command -v make >/dev/null 2>&1; then
        echo "git and make are required to install create_ap" >&2
        exit 1
    fi
    hs_install_create_ap
fi

echo "==> Installing Hotspot Toggle to $PREFIX (helper, polkit policy, schema, app)..."
hs_sudo make -C "$SCRIPT_DIR" install PREFIX="$PREFIX"

echo
echo "==> Done."
echo "    GUI:  hotspot-toggle            (or 'Hotspot' in your application menu)"
echo "    CLI:  hotspot-toggle enable | disable | toggle | status | info"
if id -nG "$USER" | grep -qwE 'sudo|wheel'; then
    echo "    You're in sudo/wheel, so toggling won't ask for a password."
else
    echo "    You'll be asked for an admin password when toggling."
fi
