"""Unit tests — no root, Wi-Fi hardware, systemd or GTK required.

    python3 -m unittest discover -s tests -v
"""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import create_ap_helper as hs  # noqa: E402
import hotspot_toggle_cli as cli  # noqa: E402

STATION_DUMP = """\
Station AA:BB:CC:DD:EE:01 (on ap0)
\tinactive time:\t120 ms
\trx bytes:\t2048
\trx packets:\t20
\ttx bytes:\t1048576
\ttx packets:\t900
\tsignal:  \t-47 [-47, -50] dBm
\tsignal avg:\t-48 dBm
\ttx bitrate:\t72.2 MBit/s MCS 7
\trx bitrate:\t65.0 MBit/s MCS 7
\tconnected time:\t3725 seconds
Station aa:bb:cc:dd:ee:02 (on ap0)
\trx bytes:\t10
\ttx bytes:\t20
\tsignal:  \t-70 dBm
\tconnected time:\t5 seconds
"""

NEIGH = """\
192.168.12.10 lladdr aa:bb:cc:dd:ee:01 REACHABLE
fe80::1234 lladdr aa:bb:cc:dd:ee:01 STALE
192.168.12.11 lladdr aa:bb:cc:dd:ee:02 STALE
192.168.12.12 FAILED
"""

LEASES = """\
1700000000 aa:bb:cc:dd:ee:01 192.168.12.10 pixel-8 01:aa:bb:cc:dd:ee:01
1700000001 aa:bb:cc:dd:ee:02 192.168.12.11 * *
garbage line
"""

IW_DEV = """\
phy#0
\tInterface ap0
\t\tifindex 5
\t\ttype AP
\tInterface wlp2s0
\t\tifindex 3
\t\ttype managed
"""


class ParserTests(unittest.TestCase):
    def test_station_dump(self):
        c = hs.parse_station_dump(STATION_DUMP)
        self.assertEqual([x.mac for x in c], ["aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02"])
        self.assertEqual(c[0].download_bytes, 1048576)  # iw "tx bytes" = to device
        self.assertEqual(c[0].upload_bytes, 2048)
        self.assertEqual(c[0].signal_dbm, -47)
        self.assertEqual(c[0].connected_s, 3725)
        self.assertEqual(c[0].tx_bitrate, "72.2 MBit/s")

    def test_neighbors_prefers_ipv4_and_skips_failed(self):
        n = hs.parse_neighbors(NEIGH)
        self.assertEqual(n["aa:bb:cc:dd:ee:01"], "192.168.12.10")
        self.assertEqual(n["aa:bb:cc:dd:ee:02"], "192.168.12.11")
        self.assertEqual(len(n), 2)

    def test_leases(self):
        l = hs.parse_leases(LEASES)
        self.assertEqual(l["aa:bb:cc:dd:ee:01"], ("192.168.12.10", "pixel-8"))
        self.assertEqual(l["aa:bb:cc:dd:ee:02"], ("192.168.12.11", ""))
        self.assertEqual(len(l), 2)

    def test_ap_interfaces(self):
        self.assertEqual(hs.parse_ap_interfaces(IW_DEV), ["ap0"])

    def test_humanize(self):
        self.assertEqual(cli.human_bytes(0), "0 B")
        self.assertEqual(cli.human_bytes(1536), "1.5 KiB")
        self.assertEqual(cli.human_bytes(None), "—")
        self.assertEqual(cli.human_duration(65), "1m 05s")
        self.assertEqual(cli.human_duration(3725), "1h 02m")


def fake_status(active, ssid="MyNet"):
    return hs.Status(active=active, ifname="wlp2s0", ap_iface="ap0", ssid=ssid,
                     internet="wlp2s0")


def run_cli(argv):
    out, errbuf = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(errbuf):
        rc = cli.dispatch(argv)
    return rc, out.getvalue(), errbuf.getvalue()


@mock.patch.object(cli, "load_settings", lambda: dict(cli.DEFAULTS, ssid="MyNet", password="secret123"))
@mock.patch.object(hs, "default_wifi_interface", lambda: "wlp2s0")
class CommandTests(unittest.TestCase):
    def test_no_args_opens_gui(self):
        self.assertIsNone(cli.dispatch([]))
        self.assertIsNone(cli.dispatch(["gui"]))

    def test_status_online_offline(self):
        with mock.patch.object(hs, "get_status", return_value=fake_status(True)), \
             mock.patch.object(hs, "count_clients", return_value=2), \
             mock.patch.object(hs, "resolve_ap_iface", return_value="ap0"):
            rc, out, _ = run_cli(["status"])
            self.assertEqual((rc, out.strip()), (0, "online"))
            rc, out, _ = run_cli(["status", "--json"])
            self.assertEqual(json.loads(out)["clients"], 2)
        with mock.patch.object(hs, "get_status", return_value=fake_status(False)):
            rc, out, _ = run_cli(["status"])
            self.assertEqual((rc, out.strip()), (3, "offline"))

    def test_enable_calls_start_and_waits(self):
        states = iter([fake_status(False), fake_status(True)])
        with mock.patch.object(hs, "get_status", side_effect=lambda _i: next(states)), \
             mock.patch.object(hs, "is_create_ap_installed", return_value=True), \
             mock.patch.object(hs, "is_helper_installed", return_value=True), \
             mock.patch.object(hs, "start", return_value="started") as start:
            rc, out, _ = run_cli(["enable", "--ssid", "Cafe", "--band", "5"])
        self.assertEqual(rc, 0)
        opts = start.call_args[0][0]
        self.assertEqual((opts.ssid, opts.band, opts.password), ("Cafe", "5", "secret123"))
        self.assertIn("online", out)

    def test_enable_when_already_online_is_noop(self):
        with mock.patch.object(hs, "get_status", return_value=fake_status(True)), \
             mock.patch.object(hs, "start") as start:
            rc, out, _ = run_cli(["on"])
        self.assertEqual(rc, 0)
        start.assert_not_called()

    def test_disable_and_toggle(self):
        seq = iter([fake_status(True), fake_status(False)])  # toggle: check, then wait
        with mock.patch.object(hs, "get_status", side_effect=lambda _i: next(seq, fake_status(False))), \
             mock.patch.object(hs, "is_helper_installed", return_value=True), \
             mock.patch.object(hs, "stop") as stop:
            # toggle → online → disable; do_disable checks status again (False) → "already offline"
            rc, out, _ = run_cli(["toggle"])
        self.assertEqual(rc, 0)
        with mock.patch.object(hs, "get_status", return_value=fake_status(False)), \
             mock.patch.object(hs, "stop") as stop:
            rc, out, _ = run_cli(["off"])
            self.assertIn("already offline", out)
            stop.assert_not_called()

    def test_error_is_reported_with_exit_1(self):
        with mock.patch.object(hs, "get_status", return_value=fake_status(False)), \
             mock.patch.object(hs, "is_create_ap_installed", return_value=False):
            rc, _, errtxt = run_cli(["enable"])
        self.assertEqual(rc, 1)
        self.assertIn("create_ap is not installed", errtxt)

    def test_info_once_json_and_text(self):
        info = hs.Info(status=fake_status(True), ap_iface="ap0",
                       clients=hs.parse_station_dump(STATION_DUMP),
                       rx_total=2058, tx_total=1048596, uptime=90, taken_at=1.0)
        info.clients[0].name, info.clients[0].ip = "pixel-8", "192.168.12.10"
        with mock.patch.object(hs, "get_status", return_value=fake_status(True)), \
             mock.patch.object(hs, "collect_info", return_value=info), \
             mock.patch.object(hs, "read_leases_direct", return_value={}):
            rc, out, _ = run_cli(["info", "--once", "--json"])
            data = json.loads(out)
            self.assertEqual(data["device_count"], 2)
            self.assertEqual(data["devices"][0]["name"], "pixel-8")
            self.assertEqual(data["total_download_bytes"], 1048596)
            rc, out, _ = run_cli(["info", "--once", "--no-auth"])
            self.assertIn("Devices connected: 2", out)
            self.assertIn("aa:bb:cc:dd:ee:01", out)
            self.assertIn("pixel-8", out)

    def test_info_offline_text(self):
        info = hs.Info(status=fake_status(False))
        with mock.patch.object(hs, "get_status", return_value=fake_status(False)), \
             mock.patch.object(hs, "collect_info", return_value=info):
            rc, out, _ = run_cli(["info", "--once"])
        self.assertEqual(rc, 3)
        self.assertIn("OFFLINE", out)

    def test_rate_tracker(self):
        rt = cli.RateTracker()
        a = hs.Info(status=fake_status(True), rx_total=1000, tx_total=5000, taken_at=10.0)
        b = hs.Info(status=fake_status(True), rx_total=3000, tx_total=15000, taken_at=12.0)
        self.assertEqual(rt.update(a), (None, None))
        self.assertEqual(rt.update(b), (5000.0, 1000.0))  # (down, up) per second

    def test_bad_usage(self):
        with self.assertRaises(SystemExit) as ctx:
            with redirect_stderr(io.StringIO()):
                cli.dispatch(["frobnicate"])
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
