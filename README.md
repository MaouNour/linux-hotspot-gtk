# Hotspot Toggle — standalone GTK app

Same functionality as the [GNOME Shell extension](../hotspot-toggle@maounour/)
version — turn a `create_ap` hotspot on/off, configure SSID/password/hidden/
PSK/WPA version/band/channel/MAC/isolation, share via QR code — but as a
normal application window that works on **any desktop environment**: GNOME,
KDE, XFCE, MATE, Cinnamon, whatever. It's just GTK4 + libadwaita, not a
Shell integration.

## What's shared with the extension, unchanged

The privileged, desktop-agnostic half of the system is reused as-is:

- `bin/gnome-hotspot-helper` — the root helper that validates input and
  supervises `create_ap` as a transient systemd unit
  (`gnome-hotspot-<iface>.service`), so start/stop is single-instance by
  construction (see the extension's README for the full "why systemd"
  writeup).
- `polkit/local.hotspot-toggle.policy` + `polkit/49-hotspot-toggle.rules` —
  pkexec pops the graphical password prompt; anyone in `sudo`/`wheel` gets
  in with no prompt at all.

**If you already installed the extension, this app works immediately with
no extra root setup** — both talk to the exact same
`/usr/local/bin/gnome-hotspot-helper` at the exact same path. `install.sh`
detects that and skips reinstalling it.

## What's new

- `hotspot_toggle_gtk.py` / `create_ap_helper.py` — a GTK4 + libadwaita
  window that replaces the Quick Settings toggle + prefs window with a
  single ordinary app window. `create_ap_helper.py` is a straight Python
  port of the extension's `createApHelper.js` (same functions, same
  pkexec/systemctl calls).
- `io.github.local.hotspot-toggle.gschema.xml` — same settings keys as the
  extension's schema, under a new non-GNOME-specific schema ID, so this app
  doesn't require the extension to be installed.
- A login autostart entry (`~/.config/autostart/...desktop`), toggled from
  the "Turn on automatically at login" switch in the app — this uses the
  standard XDG autostart mechanism, so it works on any desktop, not just
  GNOME.

## Install

### 1. GTK4 + libadwaita + PyGObject

```sh
# Debian/Ubuntu
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1

# Fedora
sudo dnf install python3-gobject gtk4 libadwaita

# Arch
sudo pacman -S python-gobject gtk4 libadwaita
```

(libadwaita ≥ 1.4 recommended — the app uses `Adw.EntryRow`,
`Adw.PasswordEntryRow`, `Adw.SwitchRow`, `Adw.SpinRow`.)

### 2. create_ap (if not already installed)

```sh
git clone https://github.com/MaouNour/Hotspot-Access-point-On-Linux.git ./create_ap
cd create_ap
sudo make install
```

### 3. This app

```sh
./install.sh
```

This installs the app to `/usr/local/share/hotspot-toggle/`, a
`hotspot-toggle` launcher to `/usr/local/bin/`, a desktop entry so it shows
up in your app menu as **Hotspot**, and (if not already present) the root
helper + polkit files.

Optional, for the QR code feature: `sudo apt install qrencode` (or `dnf
install qrencode`, `pacman -S qrencode`).

## Using it

Launch `hotspot-toggle` from your app menu or a terminal. The switch at the
top turns the hotspot on/off (a `pkexec` password prompt appears the first
time, or every time, unless you're in `sudo`/`wheel`). Everything below it
mirrors the extension's preferences: SSID, password, hidden, WPA version,
band/channel, MAC, which interface hosts the hotspot, and what to share
internet from.

**"Internet from" left on the same WiFi card (the default)** keeps the card
connected as a client while also hosting the hotspot — `create_ap`'s
virtual-interface concurrent mode.

Closing the window does **not** stop the hotspot — it's a systemd unit,
independent of whether the app is open. Reopen the app any time to check
status or turn it off.

## Feature mapping to `create_ap` flags

Same table as the extension:

| create_ap flag | Here |
|---|---|
| SSID / passphrase | SSID + Password fields |
| `-w` | WPA version dropdown |
| `--psk` | "Raw PSK" switch |
| `--hidden` | Hidden network switch |
| `--mac` | MAC address field |
| `-c` | Channel spinner |
| `--freq-band` | Frequency band dropdown |
| `--isolate-clients` | Isolate clients switch |
| `--no-virt` | "Disable virtual interface" switch |
| `-n` / internet sharing | "Internet from" dropdown |
| n/a | QR code button |

## Known limitations

Same as the extension: MAC filtering (ACLs) isn't implemented, connected-
device count is best-effort via `iw`, and this needs a WiFi driver that
supports AP mode (and, for the default concurrent mode, AP+STA at once).
