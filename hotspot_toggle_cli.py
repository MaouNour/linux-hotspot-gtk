#!/usr/bin/env python3
"""hotspot_toggle_cli.py — command-line interface for Hotspot Toggle.

    hotspot-toggle enable|disable|toggle|status|info [options]

Runs without importing GTK, so it starts instantly and works over SSH.
Saved GUI settings (GSettings) are used as defaults; every important
setting can be overridden with a flag.

Exit codes: 0 success / online, 1 error, 2 usage error, 3 offline (status).
"""
from __future__ import annotations

import argparse
import grp
import json
import os
import select
import signal
import sys
import time
from typing import Callable, Optional

import create_ap_helper as hs

SCHEMA_ID = "io.github.local.hotspot-toggle"
VERSION = "1.0.0"

EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_OFFLINE = 0, 1, 2, 3

# What the GUI's schema defaults are, used when the schema isn't installed
# (e.g. running straight from a git checkout) or GSettings is unavailable.
DEFAULTS = {
    "wifi-interface": "",
    "internet-interface": "",
    "ssid": "",
    "password": "",
    "psk-mode": False,
    "hidden": False,
    "wpa-version": "2",
    "band": "2.4",
    "channel": 1,
    "mac-address": "",
    "isolate-clients": False,
    "no-virt": False,
    "autostart": False,
}


# ---------------------------------------------------------------------------
# Settings (shared with the GUI through GSettings)
# ---------------------------------------------------------------------------

def load_settings() -> dict:
    """Saved GUI settings, falling back to defaults key by key."""
    settings = dict(DEFAULTS)
    try:
        import gi  # only Gio is needed — no GTK

        from gi.repository import Gio

        source = Gio.SettingsSchemaSource.get_default()
        if source is None or source.lookup(SCHEMA_ID, True) is None:
            return settings  # Gio.Settings.new() would abort on a missing schema
        gs = Gio.Settings.new(SCHEMA_ID)
        for key, default in DEFAULTS.items():
            if isinstance(default, bool):
                settings[key] = gs.get_boolean(key)
            elif isinstance(default, int):
                settings[key] = gs.get_int(key)
            else:
                settings[key] = gs.get_string(key)
    except Exception:  # noqa: BLE001 — PyGObject missing, no dconf, etc.
        pass
    return settings


def resolve_iface(args: argparse.Namespace, settings: dict) -> str:
    ifname = args.interface or settings["wifi-interface"] or hs.default_wifi_interface()
    if not ifname:
        raise hs.HotspotError("no Wi-Fi interface found (use --interface)")
    return ifname


def build_options(ifname: str, args: argparse.Namespace, settings: dict) -> hs.StartOptions:
    def pick(arg, key):
        return arg if arg is not None else settings[key]

    return hs.StartOptions(
        ifname=ifname,
        internet=pick(getattr(args, "internet", None), "internet-interface"),
        ssid=pick(getattr(args, "ssid", None), "ssid") or "hotspot",
        password=pick(getattr(args, "password", None), "password"),
        psk_mode=settings["psk-mode"],
        hidden=settings["hidden"],
        wpa_version=settings["wpa-version"],
        band=pick(getattr(args, "band", None), "band"),
        channel=pick(getattr(args, "channel", None), "channel"),
        mac=settings["mac-address"],
        no_virt=settings["no-virt"],
        isolate_clients=settings["isolate-clients"],
    )


def err(msg: str) -> None:
    print(f"hotspot-toggle: {msg}", file=sys.stderr)


def preflight() -> None:
    """Fail early with an actionable message instead of a pkexec error."""
    if not hs.is_create_ap_installed():
        raise hs.HotspotError("create_ap is not installed — run ./install.sh (see README)")
    if not hs.is_helper_installed():
        raise hs.HotspotError(
            "the root helper is not installed — run ./install.sh (see README)"
        )


# ---------------------------------------------------------------------------
# enable / disable / toggle / status
# ---------------------------------------------------------------------------

def _wait_for_state(ifname: str, want_active: bool, timeout: float = 10.0) -> hs.Status:
    deadline = time.monotonic() + timeout
    while True:
        status = hs.get_status(ifname)
        if status.active == want_active or time.monotonic() >= deadline:
            return status
        time.sleep(0.5)


def do_enable(ifname: str, args: argparse.Namespace, settings: dict) -> int:
    current = hs.get_status(ifname)
    if current.active and not getattr(args, "restart", False):
        print(f"already online ({current.ssid or ifname})")
        return EXIT_OK
    preflight()
    opts = build_options(ifname, args, settings)
    if not opts.password:
        err("warning: no password set — the hotspot will be an OPEN network")
    hs.start(opts)
    status = _wait_for_state(ifname, True)
    if not status.active:
        raise hs.HotspotError(
            "hotspot did not come up — see: "
            f"journalctl -u {hs.unit_name_for(ifname)} -e"
        )
    print(f"online ({opts.ssid})")
    return EXIT_OK


def do_disable(ifname: str) -> int:
    if not hs.get_status(ifname).active:
        print("already offline")
        return EXIT_OK
    preflight_helper_only()
    hs.stop(ifname)
    status = _wait_for_state(ifname, False)
    if status.active:
        raise hs.HotspotError("hotspot is still running after stop")
    print("offline")
    return EXIT_OK


def preflight_helper_only() -> None:
    if not hs.is_helper_installed():
        raise hs.HotspotError(
            "the root helper is not installed — run ./install.sh (see README)"
        )


def cmd_status(args, settings) -> int:
    ifname = resolve_iface(args, settings)
    status = hs.get_status(ifname)
    if status.active:
        status.clients = hs.count_clients(hs.resolve_ap_iface(status))
    if args.json:
        print(json.dumps({
            "online": status.active,
            "interface": ifname,
            "ap_interface": status.ap_iface if status.active else "",
            "ssid": status.ssid if status.active else "",
            "clients": status.clients if status.active else 0,
        }))
    elif args.verbose and status.active:
        print("online")
        print(f"  ssid:      {status.ssid or '?'}")
        print(f"  interface: {ifname} (AP: {status.ap_iface})")
        print(f"  devices:   {status.clients}")
    elif not args.quiet:
        print("online" if status.active else "offline")
    return EXIT_OK if status.active else EXIT_OFFLINE


# ---------------------------------------------------------------------------
# info — live view
# ---------------------------------------------------------------------------

def human_bytes(n: Optional[float]) -> str:
    if n is None:
        return "—"
    n = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024 or unit == "TiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TiB"


def human_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "—"
    s = int(seconds)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if d:
        return f"{d}d {h:02d}h"
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


class LeaseSource:
    """Device names come from create_ap's dnsmasq lease file, which is
    root-only. Strategy: read directly if we're root, otherwise ask the
    helper via pkexec — once at startup (before the screen is taken over,
    so a text-mode password prompt stays readable), and afterwards only
    when a nameless device appears AND polkit will answer silently
    (sudo/wheel members)."""

    REFRESH_MIN_SECONDS = 20

    def __init__(self, ifname: str, allow_privileged: bool = True):
        self.ifname = ifname
        self.allow_privileged = allow_privileged
        self.leases: dict[str, tuple[str, str]] = {}
        self.error: str = ""
        self._last_try = 0.0
        self._attempted = False
        self._privileged_ok = False

    @staticmethod
    def _polkit_is_silent() -> bool:
        if os.geteuid() == 0:
            return True
        names = set()
        for gid in os.getgroups():
            try:
                names.add(grp.getgrgid(gid).gr_name)
            except KeyError:
                pass
        return bool(names & {"wheel", "sudo"})

    def refresh(self, startup: bool = False, unnamed_present: bool = False) -> None:
        direct = hs.read_leases_direct(self.ifname)
        if direct is not None:
            self.leases = direct
            self.error = ""
            return
        if not self.allow_privileged:
            return
        now = time.monotonic()
        if startup:
            pass
        elif not (
            unnamed_present
            and self._polkit_is_silent()
            and (self._privileged_ok or not self._attempted)
        ):
            return
        elif now - self._last_try < self.REFRESH_MIN_SECONDS:
            return
        self._last_try = now
        self._attempted = True
        try:
            self.leases = hs.read_leases_privileged(self.ifname)
            self._privileged_ok = True
            self.error = ""
        except hs.HotspotError as e:
            self.error = str(e).splitlines()[0] if str(e) else "authorization failed"
            self._privileged_ok = False


class RateTracker:
    """Turns two byte-counter samples into bytes/second."""

    def __init__(self):
        self._prev: Optional[tuple[float, int, int]] = None

    def update(self, info: hs.Info) -> tuple[Optional[float], Optional[float]]:
        if info.rx_total is None or info.tx_total is None:
            self._prev = None
            return None, None
        cur = (info.taken_at, info.rx_total, info.tx_total)
        prev, self._prev = self._prev, cur
        if prev is None or cur[0] <= prev[0] or cur[1] < prev[1] or cur[2] < prev[2]:
            return None, None  # first sample, or the counters were reset
        dt = cur[0] - prev[0]
        # download = AP -> devices (tx); upload = devices -> AP (rx)
        return (cur[2] - prev[2]) / dt, (cur[1] - prev[1]) / dt


def info_to_dict(info: hs.Info, rates, lease_error: str = "") -> dict:
    down_rate, up_rate = rates
    return {
        "online": info.status.active,
        "interface": info.status.ifname,
        "ap_interface": info.ap_iface,
        "ssid": info.status.ssid,
        "internet": info.status.internet,
        "uptime_seconds": None if info.uptime is None else round(info.uptime),
        "device_count": len(info.clients),
        "devices": [
            {
                "mac": c.mac,
                "ip": c.ip,
                "name": c.name,
                "signal_dbm": c.signal_dbm,
                "connected_seconds": c.connected_s,
                "download_bytes": c.download_bytes,
                "upload_bytes": c.upload_bytes,
                "tx_bitrate": c.tx_bitrate,
                "rx_bitrate": c.rx_bitrate,
            }
            for c in info.clients
        ],
        "total_download_bytes": info.tx_total,
        "total_upload_bytes": info.rx_total,
        "download_rate_bps": None if down_rate is None else round(down_rate),
        "upload_rate_bps": None if up_rate is None else round(up_rate),
        "name_lookup_error": lease_error or None,
    }


def render_info(info: hs.Info, rates, lease_error: str = "", live: bool = True) -> list[str]:
    st = info.status
    if not st.active:
        return [
            "Hotspot: OFFLINE",
            "",
            f"Interface: {st.ifname or '—'}   (enable with: hotspot-toggle enable)",
        ] + (["", "Waiting for the hotspot…   q / Ctrl-C to quit"] if live else [])

    down_rate, up_rate = rates

    def rate(v):
        return "—" if v is None else human_bytes(v) + "/s"

    lines = [
        f"Hotspot: ONLINE    SSID: {st.ssid or '?'}    uptime: {human_duration(info.uptime)}",
        f"Interface: {st.ifname} (AP: {info.ap_iface})    "
        f"internet from: {st.internet or st.ifname}",
        "",
        f"Devices connected: {len(info.clients)}",
    ]

    header = ("MAC", "IP", "NAME", "SIGNAL", "ONLINE", "DOWN", "UP")
    rows = []
    for c in sorted(info.clients, key=lambda c: (c.ip or "~", c.mac)):
        rows.append((
            c.mac,
            c.ip or "—",
            c.name or "—",
            "—" if c.signal_dbm is None else f"{c.signal_dbm} dBm",
            human_duration(c.connected_s),
            human_bytes(c.download_bytes),
            human_bytes(c.upload_bytes),
        ))
    if rows:
        widths = [max(len(header[i]), *(len(r[i]) for r in rows)) for i in range(len(header))]
        widths[2] = min(widths[2], 24)
        fmt = lambda r: "  ".join(  # noqa: E731
            (r[i][: widths[i]]).ljust(widths[i]) for i in range(len(r))
        ).rstrip()
        lines.append("  " + fmt(header))
        lines.extend("  " + fmt(r) for r in rows)
    lines += [
        "",
        f"Network used (since the hotspot started):  "
        f"↓ {human_bytes(info.tx_total)}   ↑ {human_bytes(info.rx_total)}",
        f"Current speed:                             ↓ {rate(down_rate)}   ↑ {rate(up_rate)}",
    ]
    if info.clients and not any(c.name for c in info.clients) and lease_error:
        lines += ["", f"Device names unavailable: {lease_error}"]
    lines += ["", "(↓ = to devices, ↑ = from devices)" + ("   q / Ctrl-C to quit" if live else "")]
    return lines


def cmd_info(args, settings) -> int:
    ifname = resolve_iface(args, settings)
    leases = LeaseSource(ifname, allow_privileged=not args.no_auth)
    rates = RateTracker()
    interactive = sys.stdout.isatty() and not args.json and not args.once

    def sample() -> tuple[hs.Info, tuple]:
        info = hs.collect_info(ifname, leases.leases)
        if info.status.active:
            unnamed = any(not c.name for c in info.clients)
            leases.refresh(unnamed_present=unnamed)
            if unnamed and leases.leases:  # a refresh may have filled names in
                for c in info.clients:
                    lease = leases.leases.get(c.mac)
                    if lease:
                        c.ip = lease[0] or c.ip
                        c.name = lease[1]
        return info, rates.update(info)

    # Startup: fetch names now (any auth prompt appears before we draw).
    first = hs.get_status(ifname)
    if first.active and not args.no_auth:
        leases.refresh(startup=True)

    if args.once:
        info, r = sample()
        if args.json:
            print(json.dumps(info_to_dict(info, r, leases.error), indent=2))
        else:
            print("\n".join(render_info(info, r, leases.error, live=False)))
        return EXIT_OK if info.status.active else EXIT_OFFLINE

    old_term = None
    if sys.stdin.isatty() and interactive:
        import termios
        import tty

        old_term = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())

    def restore():
        if old_term is not None:
            import termios

            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_term)
        if interactive:
            sys.stdout.write("\033[?25h\033[?1049l")
            sys.stdout.flush()

    def on_sigterm(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, on_sigterm)
    if interactive:
        sys.stdout.write("\033[?1049h\033[?25l")

    try:
        while True:
            info, r = sample()
            if args.json:
                print(json.dumps(info_to_dict(info, r, leases.error)), flush=True)
            elif interactive:
                frame = render_info(info, r, leases.error)
                sys.stdout.write("\033[H" + "".join(f"{ln}\033[K\n" for ln in frame) + "\033[J")
                sys.stdout.flush()
            else:
                print("\n".join(render_info(info, r, leases.error)), "\n", flush=True)

            # Sleep, but wake early on 'q'.
            if old_term is not None:
                ready, _, _ = select.select([sys.stdin], [], [], args.interval)
                if ready and sys.stdin.read(1).lower() == "q":
                    break
            else:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        restore()
    return EXIT_OK


# ---------------------------------------------------------------------------
# Autostart (called by the login autostart entry)
# ---------------------------------------------------------------------------

def run_autostart() -> int:
    settings = load_settings()
    if not settings["autostart"]:
        return EXIT_OK
    ifname = settings["wifi-interface"] or hs.default_wifi_interface()
    if not ifname:
        err("--autostart: no Wi-Fi interface found")
        return EXIT_ERROR
    try:
        hs.start(build_options(ifname, argparse.Namespace(), settings))
    except hs.HotspotError as e:
        err(f"--autostart: {e}")
        return EXIT_ERROR
    return EXIT_OK


# ---------------------------------------------------------------------------
# Argument parsing / dispatch
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-i", "--interface", metavar="IFACE",
                        help="Wi-Fi interface (default: saved setting, else first Wi-Fi card)")

    start_opts = argparse.ArgumentParser(add_help=False)
    start_opts.add_argument("--ssid", help="network name (default: saved setting)")
    start_opts.add_argument("--password", help="passphrase, 8-63 chars (default: saved setting)")
    start_opts.add_argument("--band", choices=["2.4", "5"], help="frequency band")
    start_opts.add_argument("--channel", type=int, help="Wi-Fi channel")
    start_opts.add_argument("--internet", metavar="IFACE",
                            help="interface to share internet from ('none' = no sharing)")

    p = argparse.ArgumentParser(
        prog="hotspot-toggle",
        description="Control your Wi-Fi hotspot. Run with no command to open the GUI.",
        epilog="Settings saved in the GUI are used as defaults. "
               "Run as your normal user (not with sudo) — privileges are requested via pkexec.",
    )
    p.add_argument("-V", "--version", action="version", version=f"hotspot-toggle {VERSION}")
    sub = p.add_subparsers(dest="command", metavar="COMMAND")

    e = sub.add_parser("enable", aliases=["on", "start"], parents=[common, start_opts],
                       help="turn the hotspot on")
    e.add_argument("--restart", action="store_true",
                   help="restart with the current settings if it is already on")
    sub.add_parser("disable", aliases=["off", "stop"], parents=[common],
                   help="turn the hotspot off")
    t = sub.add_parser("toggle", parents=[common, start_opts], help="flip the hotspot on/off")
    t.add_argument("--restart", action="store_true", help=argparse.SUPPRESS)
    s = sub.add_parser("status", parents=[common],
                       help="print 'online' or 'offline' (exit code 0 / 3)")
    s.add_argument("--json", action="store_true", help="machine-readable output")
    s.add_argument("-v", "--verbose", action="store_true", help="include SSID and device count")
    s.add_argument("-q", "--quiet", action="store_true", help="no output, just the exit code")
    i = sub.add_parser("info", aliases=["watch"], parents=[common],
                       help="live view: connected devices (MAC, IP, name) and traffic")
    i.add_argument("-n", "--interval", type=float, default=2.0, metavar="SEC",
                   help="refresh interval in seconds (default 2)")
    i.add_argument("--once", action="store_true", help="print one snapshot and exit")
    i.add_argument("--json", action="store_true",
                   help="emit one JSON object per refresh (one with --once)")
    i.add_argument("--no-auth", action="store_true",
                   help="never ask for privileges; device names may be missing")
    sub.add_parser("gui", help="open the GUI")
    return p


ALIASES = {"on": "enable", "start": "enable", "off": "disable", "stop": "disable",
           "watch": "info"}


def dispatch(argv: list[str]) -> Optional[int]:
    """Run a CLI command. Returns the exit code, or None to open the GUI."""
    if not argv:
        return None
    if argv == ["--autostart"]:
        return run_autostart()
    if argv[0] == "gui":
        return None

    args = build_parser().parse_args(argv)
    if not args.command:
        return None
    command = ALIASES.get(args.command, args.command)
    if command == "info" and args.interval < 0.2:
        err("--interval must be at least 0.2 seconds")
        return EXIT_USAGE

    try:
        settings = load_settings()
        if command == "status":
            return cmd_status(args, settings)
        if command == "info":
            return cmd_info(args, settings)
        ifname = resolve_iface(args, settings)
        if command == "enable":
            return do_enable(ifname, args, settings)
        if command == "disable":
            return do_disable(ifname)
        if command == "toggle":
            if hs.get_status(ifname).active:
                return do_disable(ifname)
            return do_enable(ifname, args, settings)
    except hs.HotspotError as e:
        err(str(e))
        return EXIT_ERROR
    return EXIT_USAGE


def main() -> None:
    rc = dispatch(sys.argv[1:])
    if rc is None:
        err("no command given (try --help); open the GUI with: hotspot-toggle gui")
        rc = EXIT_USAGE
    sys.exit(rc)


if __name__ == "__main__":
    main()
