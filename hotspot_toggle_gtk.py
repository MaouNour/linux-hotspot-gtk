#!/usr/bin/env python3
"""hotspot_toggle_gtk.py — standalone GTK4/libadwaita hotspot control app.

Same functionality as the GNOME Shell extension (create_ap under the hood,
via the shared root helper + polkit setup), but works on any desktop —
GNOME, KDE, XFCE, whatever — since it's just a normal application window,
not a Shell integration.

All privileged work happens exactly like the extension: pkexec calls into
/usr/local/bin/gnome-hotspot-helper, which supervises create_ap as a
transient systemd unit. Status is read live via `systemctl is-active`.
Subprocess calls run on a background thread pool so the UI never blocks;
results are marshalled back to the main thread with GLib.idle_add.
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk, GdkPixbuf  # noqa: E402

import create_ap_helper as hotspot  # noqa: E402

APP_ID = "io.github.local.hotspot-toggle"
SCHEMA_ID = "io.github.local.hotspot-toggle"
POLL_SECONDS = 3

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="hotspot-io")


def run_async(fn, on_done=None, on_error=None):
    """Run fn() on a worker thread; call on_done(result)/on_error(exc) on
    the GTK main thread afterwards."""
    def worker():
        try:
            result = fn()
        except Exception as e:  # noqa: BLE001
            if on_error:
                def deliver_error(e=e):
                    on_error(e)
                    return False
                GLib.idle_add(deliver_error)
            return
        if on_done:
            def deliver_result(result=result):
                on_done(result)
                return False
            GLib.idle_add(deliver_result)

    _executor.submit(worker)


class QrDialog(Adw.Window):
    def __init__(self, parent, ssid: str, password: str, hidden: bool):
        super().__init__(title="Hotspot QR Code", modal=True, transient_for=parent,
                          default_width=300, default_height=340)

        self._ssid = ssid
        self._password = password
        self._hidden = hidden

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                       margin_top=18, margin_bottom=18, margin_start=18, margin_end=18)
        self.set_content(box)

        spinner = Gtk.Spinner(spinning=True, width_request=32, height_request=32,
                               halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        box.append(spinner)
        self._box = box
        self._spinner = spinner

        text = hotspot.wifi_qr_string(ssid, password, hidden)
        run_async(lambda: hotspot.render_qr_png(text), self._on_png, self._on_png_error)

    def _on_png_error(self, _exc):
        self._on_png(None)

    def _on_png(self, png_bytes: bytes | None):
        self._box.remove(self._spinner)
        if png_bytes:
            loader = GdkPixbuf.PixbufLoader()
            loader.write(png_bytes)
            loader.close()
            picture = Gtk.Picture.new_for_pixbuf(loader.get_pixbuf())
            picture.set_content_fit(Gtk.ContentFit.CONTAIN)
            self._box.append(picture)
        else:
            label = Gtk.Label(
                label='Install "qrencode" to generate a scannable QR code.\n'
                      'Showing the raw WiFi string instead:',
                wrap=True,
            )
            self._box.append(label)
            entry = Gtk.Entry(
                text=hotspot.wifi_qr_string(self._ssid, self._password, self._hidden),
                editable=False,
            )
            self._box.append(entry)


class HotspotWindow(Adw.ApplicationWindow):
    def __init__(self, app: "HotspotApp"):
        super().__init__(application=app, title="Hotspot", default_width=420, default_height=640)
        self.settings = app.settings

        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)
        toolbar_view.add_top_bar(Adw.HeaderBar())

        self.toast_overlay = Adw.ToastOverlay()
        toolbar_view.set_content(self.toast_overlay)

        scroller = Gtk.ScrolledWindow(vexpand=True)
        self.toast_overlay.set_child(scroller)

        page = Adw.PreferencesPage()
        scroller.set_child(page)

        # ---- Power group: big on/off + live status ----
        power_group = Adw.PreferencesGroup()
        page.add(power_group)

        self.power_row = Adw.ActionRow(title="Hotspot", subtitle="Checking status…")
        self.power_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.power_switch.connect("state-set", self._on_power_switch)
        self.power_row.add_suffix(self.power_switch)
        self.power_row.set_activatable_widget(self.power_switch)
        power_group.add(self.power_row)

        self.clients_row = Adw.ActionRow(title="Connected devices", subtitle="—")
        power_group.add(self.clients_row)

        if not hotspot.is_create_ap_installed() or not hotspot.is_helper_installed():
            warn_group = Adw.PreferencesGroup()
            page.add(warn_group)
            missing = "create_ap is not installed." if not hotspot.is_create_ap_installed() \
                else "Run install.sh once with sudo before this will work."
            warn_group.add(Adw.ActionRow(title="Setup needed", subtitle=f"{missing} See README.md."))

        # ---- Basics ----
        basics = Adw.PreferencesGroup(title="Hotspot")
        page.add(basics)

        self.ssid_row = Adw.EntryRow(title="Network name (SSID)")
        self.ssid_row.set_text(self.settings.get_string("ssid"))
        self.settings.bind("ssid", self.ssid_row, "text", Gio.SettingsBindFlags.DEFAULT)
        basics.add(self.ssid_row)

        self.pass_row = Adw.PasswordEntryRow(title="Password")
        self.pass_row.set_text(self.settings.get_string("password"))
        self.settings.bind("password", self.pass_row, "text", Gio.SettingsBindFlags.DEFAULT)
        gen_btn = Gtk.Button(icon_name="view-refresh-symbolic", valign=Gtk.Align.CENTER,
                              tooltip_text="Generate a random password")
        gen_btn.connect("clicked", lambda _b: self.pass_row.set_text(hotspot.random_password(12)))
        self.pass_row.add_suffix(gen_btn)
        basics.add(self.pass_row)

        self.psk_row = Adw.SwitchRow(
            title="Raw PSK",
            subtitle="Treat password above as a 64 hex-digit pre-shared key (create_ap --psk)")
        self.settings.bind("psk-mode", self.psk_row, "active", Gio.SettingsBindFlags.DEFAULT)
        basics.add(self.psk_row)

        self.hidden_row = Adw.SwitchRow(title="Hidden network",
                                         subtitle="Don't broadcast the SSID (create_ap --hidden)")
        self.settings.bind("hidden", self.hidden_row, "active", Gio.SettingsBindFlags.DEFAULT)
        basics.add(self.hidden_row)

        # ---- Share ----
        share = Adw.PreferencesGroup(title="Share", description="Scan with a phone camera to join")
        page.add(share)
        qr_row = Adw.ActionRow(title="QR code")
        qr_btn = Gtk.Button(label="Show QR Code", valign=Gtk.Align.CENTER)
        qr_btn.connect("clicked", self._on_show_qr)
        qr_row.add_suffix(qr_btn)
        share.add(qr_row)

        # ---- Radio ----
        radio = Adw.PreferencesGroup(title="Radio")
        page.add(radio)

        self.wpa_row = Adw.ComboRow(title="WPA version",
                                     model=Gtk.StringList.new(["WPA", "WPA2", "WPA + WPA2"]))
        self._wpa_map = ["1", "2", "1+2"]
        current = self.settings.get_string("wpa-version")
        self.wpa_row.set_selected(max(0, self._wpa_map.index(current)) if current in self._wpa_map else 1)
        self.wpa_row.connect("notify::selected", lambda r, _p:
                              self.settings.set_string("wpa-version", self._wpa_map[r.get_selected()]))
        radio.add(self.wpa_row)

        self.band_row = Adw.ComboRow(title="Frequency band",
                                      model=Gtk.StringList.new(["2.4 GHz", "5 GHz"]))
        self._band_map = ["2.4", "5"]
        current = self.settings.get_string("band")
        self.band_row.set_selected(self._band_map.index(current) if current in self._band_map else 0)
        self.band_row.connect("notify::selected", lambda r, _p:
                               self.settings.set_string("band", self._band_map[r.get_selected()]))
        radio.add(self.band_row)

        adjustment = Gtk.Adjustment(lower=1, upper=165, step_increment=1)
        self.channel_row = Adw.SpinRow(title="Channel", adjustment=adjustment)
        self.channel_row.set_value(self.settings.get_int("channel"))
        self.settings.bind("channel", self.channel_row, "value", Gio.SettingsBindFlags.DEFAULT)
        radio.add(self.channel_row)

        self.mac_row = Adw.EntryRow(title="MAC address (optional)")
        self.mac_row.set_text(self.settings.get_string("mac-address"))
        self.settings.bind("mac-address", self.mac_row, "text", Gio.SettingsBindFlags.DEFAULT)
        radio.add(self.mac_row)

        self.isolate_row = Adw.SwitchRow(title="Isolate clients",
                                          subtitle="create_ap --isolate-clients")
        self.settings.bind("isolate-clients", self.isolate_row, "active", Gio.SettingsBindFlags.DEFAULT)
        radio.add(self.isolate_row)

        # ---- Device ----
        device = Adw.PreferencesGroup(
            title="Device",
            description='Leave "Internet from" on the same WiFi card (or empty) to keep using '
                        "WiFi as a client while hosting the hotspot on the same card.")
        page.add(device)

        wifi_ifaces = hotspot.list_wifi_interfaces()
        self.iface_row = Adw.ComboRow(title="WiFi interface (hosts the hotspot)",
                                       model=Gtk.StringList.new(["(auto)"] + wifi_ifaces))
        self._iface_items = ["(auto)"] + wifi_ifaces
        current = self.settings.get_string("wifi-interface")
        self.iface_row.set_selected(self._iface_items.index(current) if current in self._iface_items else 0)
        self.iface_row.connect("notify::selected", self._on_iface_changed)
        device.add(self.iface_row)

        all_ifaces = hotspot.list_all_interfaces()
        self._internet_items = ["", "none"] + all_ifaces
        internet_labels = ["(same WiFi card — concurrent mode)", "none (no internet sharing)"] + all_ifaces
        self.internet_row = Adw.ComboRow(title="Internet from",
                                          model=Gtk.StringList.new(internet_labels))
        current = self.settings.get_string("internet-interface")
        self.internet_row.set_selected(
            self._internet_items.index(current) if current in self._internet_items else 0)
        self.internet_row.connect("notify::selected", self._on_internet_changed)
        device.add(self.internet_row)

        self.novirt_row = Adw.SwitchRow(title="Disable virtual interface (--no-virt)",
                                         subtitle="Only enable if your card can't do AP + client at once")
        self.settings.bind("no-virt", self.novirt_row, "active", Gio.SettingsBindFlags.DEFAULT)
        device.add(self.novirt_row)

        self.autostart_row = Adw.SwitchRow(title="Turn on automatically at login",
                                            subtitle="Adds/removes an autostart entry")
        self.autostart_row.set_active(self.settings.get_boolean("autostart"))
        self.autostart_row.connect("notify::active", self._on_autostart_toggled)
        device.add(self.autostart_row)

        # ---- Apply ----
        apply_group = Adw.PreferencesGroup(
            description="Changes take effect next time you turn the hotspot on. "
                        'Use "Apply Now" to restart it immediately.')
        page.add(apply_group)
        apply_row = Adw.ActionRow(title="Apply changes to the running hotspot")
        self.apply_btn = Gtk.Button(label="Apply Now", valign=Gtk.Align.CENTER,
                                     css_classes=["suggested-action"])
        self.apply_btn.connect("clicked", self._on_apply_now)
        apply_row.add_suffix(self.apply_btn)
        apply_group.add(apply_row)

        # state
        self._last_known_active = False
        self._suppress_switch_signal = False
        self._busy = False

        self.refresh()
        GLib.timeout_add_seconds(POLL_SECONDS, self._poll_tick)

    # ---- helpers ----

    def _current_ifname(self) -> str | None:
        ifname = self.settings.get_string("wifi-interface")
        return ifname or hotspot.default_wifi_interface()

    def _build_start_options(self, ifname: str) -> hotspot.StartOptions:
        s = self.settings
        return hotspot.StartOptions(
            ifname=ifname,
            internet=s.get_string("internet-interface"),
            ssid=s.get_string("ssid") or "hotspot",
            password=s.get_string("password"),
            psk_mode=s.get_boolean("psk-mode"),
            hidden=s.get_boolean("hidden"),
            wpa_version=s.get_string("wpa-version"),
            band=s.get_string("band"),
            channel=s.get_int("channel"),
            mac=s.get_string("mac-address"),
            no_virt=s.get_boolean("no-virt"),
            isolate_clients=s.get_boolean("isolate-clients"),
        )

    def _toast(self, text: str):
        self.toast_overlay.add_toast(Adw.Toast(title=text, timeout=4))

    # ---- combo handlers ----

    def _on_iface_changed(self, row, _param):
        sel = self._iface_items[row.get_selected()]
        self.settings.set_string("wifi-interface", "" if sel == "(auto)" else sel)

    def _on_internet_changed(self, row, _param):
        self.settings.set_string("internet-interface", self._internet_items[row.get_selected()])

    def _on_autostart_toggled(self, row, _param):
        active = row.get_active()
        self.settings.set_boolean("autostart", active)
        try:
            set_autostart_enabled(active)
        except OSError as e:
            self._toast(f"Couldn't update autostart entry: {e}")

    # ---- power switch ----

    def _on_power_switch(self, switch, state):
        # GtkSwitch's 'state-set' fires for both user clicks and
        # programmatic set_active() calls; refresh() uses
        # _suppress_switch_signal to tell them apart so polling can never
        # cascade into an unwanted restart.
        if self._suppress_switch_signal:
            return False  # allow the default state change, do nothing else
        if self._busy:
            return True  # veto the change until the current action finishes
        if state == self._last_known_active:
            return False  # already in that state, nothing to do

        self._busy = True
        self.power_row.set_subtitle("Working…")

        if state:
            ifname = self._current_ifname()
            if not ifname:
                self._busy = False
                self._toast("No WiFi interface found")
                return True  # veto, snap switch back
            opts = self._build_start_options(ifname)
            run_async(lambda: hotspot.start(opts), self._on_action_done, self._on_action_error)
        else:
            ifname = self._current_ifname()
            run_async(lambda: hotspot.stop(ifname), self._on_action_done, self._on_action_error)

        return True  # we'll set the final state ourselves once refresh() confirms it

    def _on_action_done(self, _result):
        self._busy = False
        GLib.timeout_add_seconds(1, self._refresh_once)

    def _on_action_error(self, exc):
        self._busy = False
        self._toast(f"Hotspot error: {exc}")
        self.refresh()

    def _refresh_once(self):
        self.refresh()
        return GLib.SOURCE_REMOVE

    def _on_apply_now(self, _btn):
        ifname = self._current_ifname()
        if not ifname:
            self._toast("No WiFi interface found")
            return
        self.apply_btn.set_sensitive(False)
        opts = self._build_start_options(ifname)

        def done(_result):
            self.apply_btn.set_sensitive(True)
            self._toast("Hotspot settings applied")
            self.refresh()

        def error(exc):
            self.apply_btn.set_sensitive(True)
            self._toast(f"Failed to apply: {exc}")

        run_async(lambda: hotspot.start(opts), done, error)

    def _on_show_qr(self, _btn):
        QrDialog(self, self.settings.get_string("ssid"),
                 self.settings.get_string("password"), self.settings.get_boolean("hidden"))

    # ---- status polling ----

    def _poll_tick(self):
        self.refresh()
        return GLib.SOURCE_CONTINUE

    def refresh(self):
        ifname = self._current_ifname()

        def fetch():
            status = hotspot.get_status(ifname)
            if status.active:
                status.clients = hotspot.count_clients(status.ap_iface)
            return status

        run_async(fetch, self._apply_status, lambda _e: None)

    def _apply_status(self, status: hotspot.Status):
        self._last_known_active = status.active

        self._suppress_switch_signal = True
        self.power_switch.set_active(status.active)
        self._suppress_switch_signal = False

        display_ssid = status.ssid or self.settings.get_string("ssid") or "Hotspot"
        self.power_row.set_title(display_ssid)
        self.power_row.set_subtitle("On" if status.active else "Off")
        self.clients_row.set_subtitle(str(status.clients) if status.active else "—")


class HotspotApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.settings = Gio.Settings.new(SCHEMA_ID)
        self.window = None

    def do_activate(self):
        if not self.window:
            self.window = HotspotWindow(self)
        self.window.present()


def autostart_desktop_path() -> "Path":
    from pathlib import Path
    return Path(GLib.get_user_config_dir()) / "autostart" / f"{APP_ID}-autostart.desktop"


def set_autostart_enabled(enabled: bool):
    path = autostart_desktop_path()
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        exe = shutil_which_self()
        path.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Hotspot Autostart\n"
            f"Exec={exe} --autostart\n"
            "X-GNOME-Autostart-enabled=true\n"
            "NoDisplay=true\n"
        )
    else:
        path.unlink(missing_ok=True)


def shutil_which_self() -> str:
    import shutil
    found = shutil.which("hotspot-toggle")
    if found:
        return found
    return sys.argv[0]


def run_headless_autostart():
    """--autostart: turn the hotspot on using saved settings and exit,
    without showing a window. Used by the autostart .desktop entry."""
    settings = Gio.Settings.new(SCHEMA_ID)
    if not settings.get_boolean("autostart"):
        return 0
    ifname = settings.get_string("wifi-interface") or hotspot.default_wifi_interface()
    if not ifname:
        print("hotspot-toggle --autostart: no WiFi interface found", file=sys.stderr)
        return 1
    opts = hotspot.StartOptions(
        ifname=ifname,
        internet=settings.get_string("internet-interface"),
        ssid=settings.get_string("ssid") or "hotspot",
        password=settings.get_string("password"),
        psk_mode=settings.get_boolean("psk-mode"),
        hidden=settings.get_boolean("hidden"),
        wpa_version=settings.get_string("wpa-version"),
        band=settings.get_string("band"),
        channel=settings.get_int("channel"),
        mac=settings.get_string("mac-address"),
        no_virt=settings.get_boolean("no-virt"),
        isolate_clients=settings.get_boolean("isolate-clients"),
    )
    try:
        hotspot.start(opts)
    except hotspot.HotspotError as e:
        print(f"hotspot-toggle --autostart: {e}", file=sys.stderr)
        return 1
    return 0


def main():
    if "--autostart" in sys.argv:
        sys.exit(run_headless_autostart())
    app = HotspotApp()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
