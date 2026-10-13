Name:           hotspot-toggle
Version:        @VERSION@
Release:        1%{?dist}
Summary:        GTK4 Wi-Fi hotspot toggle with a command-line interface
# NOTE: confirm the license before publishing
License:        MIT
URL:            https://github.com/MaouNour/hotspot-toggle-gtk
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  make
BuildRequires:  desktop-file-utils

Requires:       python3
Requires:       python3-gobject
Requires:       gtk4
Requires:       libadwaita >= 1.4
Requires:       polkit
Requires:       systemd
Requires:       bash
Requires:       util-linux
Requires:       procps-ng
Requires:       hostapd
Requires:       iproute
Requires:       iw
Requires:       haveged
Requires:       dnsmasq
Requires:       iptables
Requires:       qrencode

%description
Turn a create_ap Wi-Fi hotspot on and off from a GTK4/libadwaita window or from
the terminal (hotspot-toggle enable|disable|toggle|status|info). Includes a
live view of connected devices and traffic, QR-code sharing, and a root helper
that supervises create_ap as a systemd unit. create_ap is bundled privately,
so it does not clash with a system-wide copy.

%prep
%autosetup -n %{name}-%{version}

%build
# nothing to build

%install
make install DESTDIR=%{buildroot} PREFIX=%{_prefix} BUNDLE_CREATE_AP=1
rm -f %{buildroot}%{_datadir}/doc/%{name}/README.md

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/io.github.local.hotspot-toggle.desktop

%posttrans
glib-compile-schemas %{_datadir}/glib-2.0/schemas &>/dev/null || :
gtk-update-icon-cache -q -t -f %{_datadir}/icons/hicolor &>/dev/null || :

%postun
glib-compile-schemas %{_datadir}/glib-2.0/schemas &>/dev/null || :

%files
%doc README.md
%license %{_datadir}/doc/%{name}/create_ap.LICENSE
%{_bindir}/hotspot-toggle
%{_bindir}/gnome-hotspot-helper
%{_datadir}/hotspot-toggle/
%{_prefix}/lib/hotspot-toggle/
%{_datadir}/polkit-1/actions/local.hotspot-toggle.policy
%config(noreplace) %{_sysconfdir}/polkit-1/rules.d/49-hotspot-toggle.rules
%{_datadir}/glib-2.0/schemas/io.github.local.hotspot-toggle.gschema.xml
%{_datadir}/applications/io.github.local.hotspot-toggle.desktop
%{_datadir}/icons/hicolor/scalable/apps/io.github.local.hotspot-toggle.svg
%{_datadir}/bash-completion/completions/hotspot-toggle
%{_mandir}/man1/hotspot-toggle.1*

%changelog
* @RPMDATE@ MaouNour <noreply@users.noreply.github.com> - @VERSION@-1
- Release @VERSION@
