#!/bin/bash
# install.sh — installs the standalone GTK hotspot app for the current user,
# plus (if not already present) the shared root helper + polkit setup.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${PREFIX:-/usr/local}"
APP_LIB_DIR="$PREFIX/share/hotspot-toggle"

echo "==> Checking dependencies..."
python3 - <<'PYEOF' || { echo "Missing PyGObject/GTK4/libadwaita. See README.md for install commands for your distro."; exit 1; }
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw
print("    PyGObject + GTK4 + libadwaita OK")
PYEOF

echo "==> Checking create_ap is installed..."
if ! command -v create_ap >/dev/null 2>&1; then
    cat <<'EOF'
create_ap was not found on PATH.
Install it first:

    git clone https://github.com/oblique/create_ap
    cd create_ap
    sudo make install

Re-run this script after installing create_ap.
EOF
    exit 1
fi
echo "    found: $(command -v create_ap)"

# --- root helper + polkit (shared with the GNOME Shell extension, if you
#     installed that too — this is idempotent and safe to run again) ---
if [[ ! -x /usr/local/bin/gnome-hotspot-helper ]]; then
    echo "==> Installing root helper + polkit policy (needs sudo)..."
    sudo install -o root -g root -m 0755 "$SCRIPT_DIR/bin/gnome-hotspot-helper" /usr/local/bin/gnome-hotspot-helper
    sudo install -o root -g root -m 0644 "$SCRIPT_DIR/polkit/local.hotspot-toggle.policy" /usr/share/polkit-1/actions/local.hotspot-toggle.policy
    sudo install -o root -g root -m 0644 "$SCRIPT_DIR/polkit/49-hotspot-toggle.rules" /etc/polkit-1/rules.d/49-hotspot-toggle.rules
    sudo systemctl restart polkit 2>/dev/null || sudo service polkit restart 2>/dev/null || true
    if id -nG "$USER" | grep -qwE 'sudo|wheel'; then
        echo "    Done. You're in sudo/wheel, so toggling won't prompt for a password."
    else
        echo "    Done. Toggling will prompt for an admin password each time (cached briefly)."
    fi
else
    echo "==> Root helper already installed (shared with the extension, if present) — skipping."
fi

# --- gschema (system-wide, so it works regardless of which user runs the app) ---
echo "==> Installing GSettings schema (needs sudo)..."
sudo install -d /usr/share/glib-2.0/schemas
sudo install -o root -g root -m 0644 "$SCRIPT_DIR/schemas/io.github.local.hotspot-toggle.gschema.xml" /usr/share/glib-2.0/schemas/
sudo glib-compile-schemas /usr/share/glib-2.0/schemas/

# --- app files ---
echo "==> Installing application to $APP_LIB_DIR"
sudo install -d "$APP_LIB_DIR"
sudo install -o root -g root -m 0644 "$SCRIPT_DIR/hotspot_toggle_gtk.py" "$APP_LIB_DIR/"
sudo install -o root -g root -m 0644 "$SCRIPT_DIR/create_ap_helper.py" "$APP_LIB_DIR/"

echo "==> Installing launcher to $PREFIX/bin/hotspot-toggle"
sudo tee "$PREFIX/bin/hotspot-toggle" > /dev/null <<EOF
#!/bin/sh
exec python3 "$APP_LIB_DIR/hotspot_toggle_gtk.py" "\$@"
EOF
sudo chmod +x "$PREFIX/bin/hotspot-toggle"

echo "==> Installing desktop entry"
sudo install -d /usr/share/applications
sudo install -o root -g root -m 0644 "$SCRIPT_DIR/data/io.github.local.hotspot-toggle.desktop" /usr/share/applications/
sudo update-desktop-database /usr/share/applications 2>/dev/null || true

echo "==> Done. Launch it with 'hotspot-toggle' or from your application menu as 'Hotspot'."
