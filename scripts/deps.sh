#!/bin/bash
# deps.sh — distro detection + dependency installation for Hotspot Toggle.
# Sourced by install.sh and by the AppImage first-run setup; not run directly.
# Package lists mirror the packaging/ metadata (rpm spec, debian/control,
# PKGBUILD) — keep them in sync.

hs_sudo() {
    # Run a command as root: directly if we already are, otherwise via sudo.
    if [[ $EUID -eq 0 ]]; then "$@"; else sudo "$@"; fi
}

hs_detect_pm() {
    # Prints dnf | pacman | apt, or returns 1 on an unsupported distro.
    local ids=""
    if [[ -r /etc/os-release ]]; then
        ids=" $( . /etc/os-release; echo "${ID:-} ${ID_LIKE:-}" ) "
    fi
    case "$ids" in
        *" fedora "*|*" rhel "*|*" centos "*) echo dnf; return 0 ;;
        *" arch "*)                           echo pacman; return 0 ;;
        *" debian "*|*" ubuntu "*)            echo apt; return 0 ;;
    esac
    # Fall back to whatever package manager is present.
    if   command -v dnf    >/dev/null 2>&1; then echo dnf
    elif command -v pacman >/dev/null 2>&1; then echo pacman
    elif command -v apt-get >/dev/null 2>&1; then echo apt
    else return 1
    fi
}

# Runtime dependencies: the hotspot stack (create_ap's requirements), polkit
# for the password prompt, and PyGObject/GTK4/libadwaita (>= 1.4) for the GUI.
hs_runtime_packages() {
    case "$1" in
        dnf)
            echo python3 python3-gobject gtk4 libadwaita polkit systemd \
                 bash util-linux procps-ng hostapd iproute iw haveged dnsmasq iptables qrencode ;;
        pacman)
            echo python python-gobject gtk4 libadwaita polkit systemd \
                 bash util-linux procps-ng hostapd iproute2 iw wireless_tools haveged dnsmasq iptables qrencode ;;
        apt)
            local pk=policykit-1
            apt-cache show pkexec >/dev/null 2>&1 && pk=pkexec
            echo python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 "$pk" systemd \
                 bash util-linux procps hostapd iproute2 iw wireless-tools haveged dnsmasq iptables qrencode ;;
        *) return 1 ;;
    esac
}

# Only needed to fetch and install create_ap from git.
hs_build_packages() { echo git make; }

hs_install_packages() {
    local pm=$1; shift
    case "$pm" in
        dnf)    hs_sudo dnf install -y "$@" ;;
        pacman) hs_sudo pacman -S --needed --noconfirm "$@" ;;
        apt)    hs_sudo apt-get update
                hs_sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y "$@" ;;
    esac
}

hs_install_deps() {
    local pm pkgs
    pm=$(hs_detect_pm) || {
        echo "Unsupported distribution: install the packages listed in README.md manually." >&2
        return 1
    }
    read -r -a pkgs <<<"$(hs_runtime_packages "$pm") $(hs_build_packages)"
    echo "==> Installing dependencies with $pm: ${pkgs[*]}"
    hs_install_packages "$pm" "${pkgs[@]}"
}

# Installs the create_ap fork system-wide, exactly as documented in the README.
hs_install_create_ap() {
    local repo=${CREATE_AP_REPO:-https://github.com/MaouNour/Hotspot-Access-point-On-Linux.git}
    local tmp; tmp=$(mktemp -d)
    echo "==> Installing create_ap from $repo"
    git clone --depth 1 "$repo" "$tmp/create_ap"
    ( cd "$tmp/create_ap" && hs_sudo make install )
    rm -rf "$tmp"
}

# True if the GUI toolkit stack imports (libadwaita >= 1.4 needed for ToolbarView).
hs_gui_stack_ok() {
    python3 - <<'PY' >/dev/null 2>&1
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw
assert hasattr(Adw, "ToolbarView")
PY
}
