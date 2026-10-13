"""create_ap_helper.py

Python port of the extension's createApHelper.js — talks to the same
/usr/local/bin/gnome-hotspot-helper via pkexec, and to systemd directly for
status. Shared, desktop-agnostic logic: nothing here is GNOME-specific.

All subprocess calls are synchronous (plain `subprocess.run`); callers
running inside a GTK main loop should invoke these from a background
thread and marshal results back with GLib.idle_add — see
hotspot_toggle_gtk.py. This module deliberately has no GTK/GObject imports so
the command-line interface (hotspot_toggle_cli.py) can use it quickly and on
headless machines.
"""
from __future__ import annotations

import glob
import json
import os
import random
import shutil
import re
import string
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# The root helper is installed to /usr/local/bin by install.sh and to
# /usr/bin by the distro packages (the polkit policy pins the exact path, so
# the helper and its policy file always live side by side).
HELPER_CANDIDATES = (
    "/usr/local/bin/gnome-hotspot-helper",
    "/usr/bin/gnome-hotspot-helper",
)
# create_ap may be on PATH (system-wide `make install`) or bundled privately
# by the distro packages / AppImage setup.
CREATE_AP_CANDIDATES = (
    "/usr/local/bin/create_ap",
    "/usr/local/lib/hotspot-toggle/create_ap",
    "/usr/lib/hotspot-toggle/create_ap",
)
STATUS_FILE = Path("/run/gnome-hotspot-toggle/status.json")


class HotspotError(Exception):
    pass


def _run(argv: list[str], timeout: int = 30) -> str:
    """Run a command, raise HotspotError with stderr/stdout on failure."""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as e:
        raise HotspotError(str(e)) from e
    except subprocess.TimeoutExpired as e:
        raise HotspotError(f"timed out: {' '.join(argv)}") from e

    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "command failed").strip()
        raise HotspotError(msg)
    return proc.stdout.strip()


def _run_tolerant(argv: list[str], timeout: int = 10) -> str:
    """Like _run, but a non-zero exit is a normal outcome (systemctl is-active)."""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    return (proc.stdout or "").strip()


def find_helper() -> str:
    for path in HELPER_CANDIDATES:
        if os.access(path, os.X_OK):
            return path
    return HELPER_CANDIDATES[0]


HELPER = find_helper()  # kept for backwards compatibility


def is_helper_installed() -> bool:
    return os.access(find_helper(), os.X_OK)


def is_create_ap_installed() -> bool:
    return shutil.which("create_ap") is not None or any(
        os.access(p, os.X_OK) for p in CREATE_AP_CANDIDATES
    )


def is_systemd_available() -> bool:
    return shutil.which("systemd-run") is not None


def unit_name_for(ifname: str) -> str:
    return f"gnome-hotspot-{ifname}.service"


def list_wifi_interfaces() -> list[str]:
    ifaces = []
    net = Path("/sys/class/net")
    if not net.is_dir():
        return ifaces
    for entry in sorted(net.iterdir()):
        if (entry / "wireless").is_dir() or (entry / "phy80211").exists():
            ifaces.append(entry.name)
    return ifaces


def list_all_interfaces() -> list[str]:
    net = Path("/sys/class/net")
    if not net.is_dir():
        return []
    return sorted(e.name for e in net.iterdir() if e.name != "lo")


def default_wifi_interface() -> Optional[str]:
    ifaces = list_wifi_interfaces()
    return ifaces[0] if ifaces else None


def _read_metadata() -> dict:
    try:
        return json.loads(STATUS_FILE.read_text())
    except (OSError, ValueError):
        return {}


@dataclass
class Status:
    active: bool = False
    ifname: str = ""
    ap_iface: str = ""
    ssid: str = ""
    internet: str = ""
    clients: int = 0


def get_status(ifname: Optional[str]) -> Status:
    """Live status. `active` comes straight from systemd, not a file that
    could go stale if e.g. hostapd crashed without telling us."""
    if not ifname:
        return Status()

    unit = unit_name_for(ifname)
    state = _run_tolerant(["systemctl", "is-active", unit])
    active = state in ("active", "activating")

    meta = _read_metadata()
    meta_matches = meta.get("unit") == unit

    return Status(
        active=active,
        ifname=ifname,
        ap_iface=(meta.get("ap_iface") if meta_matches else ifname) or ifname,
        ssid=(meta.get("ssid") if meta_matches else "") or "",
        internet=(meta.get("internet") if meta_matches else "") or "",
    )


def count_clients(ap_iface: Optional[str]) -> int:
    if not ap_iface:
        return 0
    try:
        out = _run(["iw", "dev", ap_iface, "station", "dump"], timeout=5)
    except HotspotError:
        return 0
    return sum(1 for line in out.splitlines() if line.startswith("Station "))


# ---------------------------------------------------------------------------
# Live info: connected devices (MAC / IP / name) and traffic
# ---------------------------------------------------------------------------

MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


@dataclass
class Client:
    mac: str
    ip: str = ""
    name: str = ""
    signal_dbm: Optional[int] = None
    connected_s: Optional[int] = None
    # Byte counters are from the AP's point of view, so we flip them into
    # the user's point of view: "download" is what the device received.
    download_bytes: int = 0  # iw "tx bytes" (AP -> device)
    upload_bytes: int = 0  # iw "rx bytes" (device -> AP)
    tx_bitrate: str = ""
    rx_bitrate: str = ""


def _first_int(text: str) -> Optional[int]:
    m = re.search(r"-?\d+", text or "")
    return int(m.group()) if m else None


def _bitrate(text: str) -> str:
    """'72.2 MBit/s MCS 7 short GI' -> '72.2 MBit/s'."""
    m = re.match(r"\s*([\d.]+)\s*(\S+)", text or "")
    return f"{m.group(1)} {m.group(2)}" if m else ""


def parse_station_dump(text: str) -> list[Client]:
    """Parse `iw dev <iface> station dump` output."""
    clients: list[Client] = []
    cur: Optional[Client] = None
    for raw in text.splitlines():
        line = raw.strip()
        if raw.startswith("Station "):
            parts = raw.split()
            mac = parts[1].lower() if len(parts) > 1 else ""
            cur = Client(mac=mac)
            clients.append(cur)
            continue
        if cur is None or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if key == "rx bytes":
            cur.upload_bytes = _first_int(val) or 0
        elif key == "tx bytes":
            cur.download_bytes = _first_int(val) or 0
        elif key == "signal":
            cur.signal_dbm = _first_int(val)
        elif key == "connected time":
            cur.connected_s = _first_int(val)
        elif key == "tx bitrate":
            cur.tx_bitrate = _bitrate(val)
        elif key == "rx bitrate":
            cur.rx_bitrate = _bitrate(val)
    return [c for c in clients if MAC_RE.match(c.mac)]


def parse_neighbors(text: str) -> dict[str, str]:
    """Parse `ip neigh show dev <iface>` into {mac: ip}; prefers IPv4."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        tok = line.split()
        if "lladdr" not in tok or not tok:
            continue
        i = tok.index("lladdr")
        if i + 1 >= len(tok) or tok[-1] in ("FAILED", "INCOMPLETE"):
            continue
        mac, ip = tok[i + 1].lower(), tok[0]
        if mac not in out or (":" in out[mac] and ":" not in ip):
            out[mac] = ip
    return out


def parse_leases(text: str) -> dict[str, tuple[str, str]]:
    """Parse dnsmasq lease lines: `expiry mac ip hostname clientid`."""
    out: dict[str, tuple[str, str]] = {}
    for line in text.splitlines():
        tok = line.split()
        if len(tok) < 4 or not MAC_RE.match(tok[1].lower()):
            continue
        name = "" if tok[3] == "*" else tok[3]
        out[tok[1].lower()] = (tok[2], name)
    return out


def parse_ap_interfaces(iw_dev_output: str) -> list[str]:
    """Interfaces of type AP from `iw dev`."""
    result, current = [], None
    for line in iw_dev_output.splitlines():
        line = line.strip()
        if line.startswith("Interface "):
            current = line.split(None, 1)[1]
        elif line.startswith("type ") and current:
            if line.split(None, 1)[1].strip() == "AP":
                result.append(current)
            current = None
    return result


def list_ap_interfaces() -> list[str]:
    return parse_ap_interfaces(_run_tolerant(["iw", "dev"], timeout=5))


def read_leases_direct(ifname: str) -> Optional[dict[str, tuple[str, str]]]:
    """Read create_ap's dnsmasq lease file. It lives in a root-only temp dir,
    so this works only when running as root; returns None if unreadable."""
    found = False
    merged: dict[str, tuple[str, str]] = {}
    for path in glob.glob(f"/tmp/create_ap.{ifname}.conf.*/dnsmasq.leases"):
        try:
            merged.update(parse_leases(Path(path).read_text()))
            found = True
        except OSError:
            continue
    return merged if found else None


def read_leases_privileged(ifname: str) -> dict[str, tuple[str, str]]:
    """Ask the root helper for the lease file (pkexec; silent for sudo/wheel
    members, otherwise a password prompt). Raises HotspotError on failure."""
    out = _run(["pkexec", find_helper(), "leases", "--ifname", ifname], timeout=60)
    return parse_leases(out)


def read_iface_counters(iface: str) -> Optional[tuple[int, int]]:
    """(rx_bytes, tx_bytes) of the AP interface, from sysfs. For an AP, rx is
    traffic *from* devices (their upload) and tx is *to* devices."""
    base = Path("/sys/class/net") / iface / "statistics"
    try:
        return (
            int((base / "rx_bytes").read_text()),
            int((base / "tx_bytes").read_text()),
        )
    except (OSError, ValueError):
        return None


def uptime_seconds(unit: str) -> Optional[float]:
    """Seconds since the systemd unit became active (None if unknown)."""
    out = _run_tolerant(
        ["systemctl", "show", unit, "-p", "ActiveEnterTimestampMonotonic", "--value"]
    )
    try:
        started_us = int(out)
    except ValueError:
        return None
    if started_us <= 0:
        return None
    return max(0.0, time.monotonic() - started_us / 1_000_000)


def resolve_ap_iface(status: "Status") -> str:
    """The interface that actually carries clients. create_ap's virtual
    interface name is scraped from the journal by the helper; if that
    missed, fall back to whichever interface `iw` says is in AP mode."""
    candidates = [status.ap_iface] if status.ap_iface else []
    aps = list_ap_interfaces()
    for name in candidates:
        if name in aps:
            return name
    if aps:
        return aps[0]
    return status.ap_iface or status.ifname


@dataclass
class Info:
    status: Status
    ap_iface: str = ""
    clients: list[Client] = field(default_factory=list)
    rx_total: Optional[int] = None  # bytes received from devices (upload)
    tx_total: Optional[int] = None  # bytes sent to devices (download)
    uptime: Optional[float] = None
    taken_at: float = 0.0


def collect_info(
    ifname: Optional[str],
    leases: Optional[dict[str, tuple[str, str]]] = None,
) -> Info:
    status = get_status(ifname)
    info = Info(status=status, taken_at=time.monotonic())
    if not status.active:
        return info

    info.ap_iface = resolve_ap_iface(status)
    info.uptime = uptime_seconds(unit_name_for(status.ifname))

    try:
        dump = _run(["iw", "dev", info.ap_iface, "station", "dump"], timeout=5)
    except HotspotError:
        dump = ""
    info.clients = parse_station_dump(dump)

    neighbors = parse_neighbors(
        _run_tolerant(["ip", "neigh", "show", "dev", info.ap_iface], timeout=5)
    )
    for c in info.clients:
        lease = (leases or {}).get(c.mac)
        c.ip = (lease[0] if lease else "") or neighbors.get(c.mac, "")
        c.name = lease[1] if lease else ""

    counters = read_iface_counters(info.ap_iface)
    if counters:
        info.rx_total, info.tx_total = counters
    status.clients = len(info.clients)
    return info


@dataclass
class StartOptions:
    ifname: str
    internet: str = ""
    ssid: str = ""
    password: str = ""
    psk_mode: bool = False
    hidden: bool = False
    wpa_version: str = "2"
    band: str = "2.4"
    channel: int = 1
    mac: str = ""
    no_virt: bool = False
    isolate_clients: bool = False


def start(opts: StartOptions) -> str:
    """Start the hotspot. Raises HotspotError on failure (including the user
    cancelling the pkexec password prompt)."""
    args = [
        "pkexec", find_helper(), "start",
        "--ifname", opts.ifname,
        "--internet", opts.internet or opts.ifname,
        "--ssid", opts.ssid,
        "--password", opts.password or "",
        "--channel", str(opts.channel or 1),
        "--wpa", opts.wpa_version or "2",
        "--band", opts.band or "2.4",
        "--hidden", "1" if opts.hidden else "0",
        "--psk", "1" if opts.psk_mode else "0",
        "--no-virt", "1" if opts.no_virt else "0",
        "--isolate", "1" if opts.isolate_clients else "0",
    ]
    if opts.mac:
        args += ["--mac", opts.mac]
    return _run(args, timeout=60)


def stop(ifname: str) -> str:
    return _run(["pkexec", find_helper(), "stop", "--ifname", ifname], timeout=60)


def wifi_qr_string(ssid: str, password: str, hidden: bool) -> str:
    def esc(s: str) -> str:
        out = []
        for ch in s:
            if ch in '\\;,:"':
                out.append("\\")
            out.append(ch)
        return "".join(out)

    t = "WPA" if password else "nopass"
    return f"WIFI:T:{t};S:{esc(ssid)};P:{esc(password) if password else ''};H:{'true' if hidden else 'false'};;"


def render_qr_png(text: str) -> Optional[bytes]:
    if shutil.which("qrencode") is None:
        return None
    try:
        proc = subprocess.run(
            ["qrencode", "-t", "PNG", "-o", "-", "-s", "8", text],
            capture_output=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def random_password(length: int = 12) -> str:
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    return "".join(random.SystemRandom().choice(chars) for _ in range(length))
