# Hotspot Toggle — GTK app + command line

Turn a [`create_ap`](https://github.com/MaouNour/Hotspot-Access-point-On-Linux) Wi-Fi hotspot on and off from a
GTK4 + libadwaita window **or from the terminal**, on any desktop (GNOME, KDE, XFCE, …).

```sh
hotspot-toggle                 # open the window
hotspot-toggle enable          # turn it on   (aliases: on, start)
hotspot-toggle disable         # turn it off  (aliases: off, stop)
hotspot-toggle toggle
hotspot-toggle status          # prints "online" or "offline"
hotspot-toggle info            # live view: devices (MAC, IP, name) + traffic
```

## Install

### Option 1 — one-step installer (Fedora, Ubuntu/Debian, Arch and derivatives)

```sh
./install.sh
```

It detects your distro, installs every dependency (`dnf` / `apt` / `pacman`), installs `create_ap` if you don't
already have it, then installs the app, root helper and polkit policy to `/usr/local`.
`./install.sh --no-deps` skips the package step, `./install.sh --uninstall` removes the app.

### Option 2 — a package from the Releases page

Each release ships all dependencies as package requirements, so your package manager pulls them in automatically
(`create_ap` is bundled privately and never clashes with a system copy):

| Distro | Install |
|---|---|
| Fedora / RHEL-likes | `sudo dnf install ./hotspot-toggle-*.noarch.rpm` |
| Ubuntu / Debian | `sudo apt install ./hotspot-toggle_*_all.deb` |
| Arch / Manjaro | `sudo pacman -U ./hotspot-toggle-*.pkg.tar.zst` |
| Anything else | `chmod +x Hotspot-Toggle-*.AppImage && ./Hotspot-Toggle-*.AppImage` |

Don't combine a package with `./install.sh` — pick one.

**AppImage note:** it contains the app, CLI and `create_ap`, but not GTK4/Python (the host provides those).
On first run — and only when something is missing — it installs the host dependencies, root helper and polkit
policy once, with a single admin-password prompt (`--setup` forces it again, `HOTSPOT_SKIP_SETUP=1` skips the check).
If it complains about FUSE, run it with `--appimage-extract-and-run`.

### Option 3 — by hand

1. **Install `create_ap`** (if you don't already have it):

   ```sh
   git clone https://github.com/MaouNour/Hotspot-Access-point-On-Linux.git ./create_ap
   cd create_ap
   sudo make install
   ```

2. **Dependencies**

   ```sh
   # Fedora
   sudo dnf install bash util-linux procps-ng hostapd iproute iw haveged dnsmasq iptables qrencode \
       python3-gobject gtk4 libadwaita polkit

   # Arch Linux
   sudo pacman -S bash util-linux procps-ng hostapd iproute2 iw wireless_tools haveged dnsmasq iptables qrencode \
       python-gobject gtk4 libadwaita polkit

   # Ubuntu / Debian
   sudo apt update
   sudo apt install bash util-linux procps hostapd iproute2 iw wireless-tools haveged dnsmasq iptables qrencode \
       python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 pkexec     # "policykit-1" instead of pkexec on older releases
   ```

3. **The app**: `sudo make install` (or `sudo make install PREFIX=/usr`).

Requires **libadwaita ≥ 1.4** for the window (Ubuntu 24.04+, Fedora 39+, current Arch). Without it the command line
still works if you install the files by hand, but the packages require it.

## Command line

```
hotspot-toggle [-i IFACE] enable [--ssid S] [--password P] [--band 2.4|5] [--channel N] [--internet IFACE] [--restart]
hotspot-toggle [-i IFACE] disable
hotspot-toggle [-i IFACE] toggle
hotspot-toggle [-i IFACE] status [--json] [-v]
hotspot-toggle [-i IFACE] info   [-n SEC] [--once] [--json] [--no-auth]
```

Whatever you saved in the window (SSID, password, band, …) is the default; flags override it for that run.
Run it as your normal user, **not with sudo** — it asks for privileges through `pkexec` when it needs them
(and not at all if you're in the `sudo`/`wheel` group). `man hotspot-toggle` and tab completion are installed.

**`status`** prints `online` or `offline`. Exit code is `0` online / `3` offline, so it works in scripts:
`hotspot-toggle status -q || hotspot-toggle enable`. `-v` adds SSID and device count; `--json` is machine-readable.

**`info`** stays open and refreshes every 2 s (`q` or Ctrl-C to quit):

```
Hotspot: ONLINE    SSID: MyNet    uptime: 12m 34s
Interface: wlp2s0 (AP: ap0)    internet from: wlp2s0

Devices connected: 2
  MAC                IP             NAME     SIGNAL   ONLINE  DOWN     UP
  aa:bb:cc:dd:ee:01  192.168.12.10  pixel-8  -47 dBm  1h 02m  1.0 MiB  2.0 KiB
  aa:bb:cc:dd:ee:02  192.168.12.11  —        -70 dBm  5s      20 B     10 B

Network used (since the hotspot started):  ↓ 1.0 MiB   ↑ 2.0 KiB
Current speed:                             ↓ 4.9 KiB/s   ↑ 1000 B/s

(↓ = to devices, ↑ = from devices)   q / Ctrl-C to quit
```

* MACs, signal, time connected and per-device traffic come from `iw`; IPs from the neighbour table.
* **Device names** come from `create_ap`'s dnsmasq lease file, which only root can read. `info` fetches it through the
  root helper (silent for `sudo`/`wheel` members, otherwise one password prompt at startup). Devices that don't send a
  hostname show `—`. `--no-auth` skips this entirely.
* `info --json` prints one JSON object per refresh (a single one with `--once`).
* Exit codes: `0` ok, `1` error, `2` usage error, `3` offline (`status`, `info --once`).

## How it works

* `hotspot_toggle_gtk.py` — the window. `hotspot_toggle_cli.py` — the commands (never imports GTK, so it is fast and
  works over SSH). `create_ap_helper.py` — shared logic. The GUI and CLI share settings through GSettings.
* `bin/gnome-hotspot-helper` — root helper, run via `pkexec`. It validates every argument and supervises `create_ap`
  as a transient systemd unit (`gnome-hotspot-<iface>.service`), so start/stop is single-instance by construction.
  Closing the window does **not** stop the hotspot.
* `polkit/` — pins `pkexec` to the helper's exact path; `sudo`/`wheel` members get no prompt.
* The helper is the same one used by the
  [GNOME Shell extension](https://github.com/MaouNour/hotspot-gnome-extension); the two can coexist.

## Building packages

```sh
make dist                       # source tarball in dist/ (fetches a pinned create_ap snapshot)
packaging/build.sh              # deb + rpm + arch + AppImage in clean containers (podman or docker)
packaging/build.sh deb rpm      # only some formats
```

Without containers, run `packaging/build-deb.sh`, `build-rpm.sh`, `build-arch.sh` (as a normal user) or
`build-appimage.sh` on a matching system. Output goes to `dist/`.

**GitHub Actions** (`.github/workflows/`):

| Workflow | When | What |
|---|---|---|
| `ci.yml` | push / PR | unit tests, shellcheck, desktop-file validation, then builds all four packages |
| `release.yml` | tag `vX.Y.Z` | verifies the tag matches `VERSION`, builds everything, publishes a GitHub Release with `SHA256SUMS` |

Release: edit `VERSION`, commit, `git tag v1.0.1 && git push --tags`.
The bundled `create_ap` is pinned in `packaging/create_ap.ref` (a full commit SHA) so builds are reproducible;
bump it to ship a newer `create_ap`.

Package dependency lists live in `scripts/deps.sh` (installer/AppImage), `packaging/rpm/hotspot-toggle.spec`,
`packaging/debian/control` and `packaging/arch/PKGBUILD` — keep them in sync.

## Tests

```sh
make test      # parsers, CLI commands, live-view rendering — no root or Wi-Fi hardware needed
```

## Limitations

* Needs a Wi-Fi driver with AP mode (and AP+STA for the default same-card concurrent mode).
* MAC filtering (ACLs) isn't implemented.
* Per-device traffic counters reset when a device reconnects; the "network used" total is the AP interface's counter.
* Packages and `install.sh` both own `gnome-hotspot-helper`; don't install both at once.
* Package metadata lists the license as MIT as a placeholder — set the real license before publishing.
