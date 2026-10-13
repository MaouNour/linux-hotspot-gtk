#!/bin/bash
# Root-side one-time setup for the AppImage (run via pkexec from AppRun, from a
# temp copy of this directory). Installs distro dependencies, the root helper,
# the polkit policy/rules and a private create_ap.
set -euo pipefail
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ $EUID -eq 0 ]] || { echo "setup.sh must run as root" >&2; exit 1; }
# shellcheck source=/dev/null
source "$D/deps.sh"

hs_install_deps || echo "warning: could not install dependencies automatically — see README.md" >&2

install -Dm755 "$D/gnome-hotspot-helper" /usr/local/bin/gnome-hotspot-helper
install -Dm644 "$D/local.hotspot-toggle.policy" /usr/share/polkit-1/actions/local.hotspot-toggle.policy
install -Dm644 "$D/49-hotspot-toggle.rules" /etc/polkit-1/rules.d/49-hotspot-toggle.rules
install -Dm755 "$D/create_ap" /usr/local/lib/hotspot-toggle/create_ap
echo "Hotspot Toggle setup complete."
