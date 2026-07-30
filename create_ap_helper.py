"""create_ap_helper.py

Python port of the extension's createApHelper.js — talks to the same
/usr/local/bin/gnome-hotspot-helper via pkexec, and to systemd directly for
status. Shared, desktop-agnostic logic: nothing here is GNOME-specific.

All subprocess calls are synchronous (plain `subprocess.run`); callers
running inside a GTK main loop should invoke these from a background
thread and marshal results back with GLib.idle_add — see hotspot_app.py.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import string
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

HELPER = "/usr/local/bin/gnome-hotspot-helper"
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


def is_helper_installed() -> bool:
    return os.access(HELPER, os.X_OK)


def is_create_ap_installed() -> bool:
    return shutil.which("create_ap") is not None


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
        "pkexec", HELPER, "start",
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
    return _run(["pkexec", HELPER, "stop", "--ifname", ifname], timeout=60)


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
