# Hotspot Toggle — install / package helper.
#
#   make install                       # to /usr/local (needs root)
#   make install PREFIX=/usr DESTDIR=pkgroot BUNDLE_CREATE_AP=1   # packaging
#   make uninstall
#   make dist                          # dist/hotspot-toggle-<version>.tar.gz
#   make test
#
# BUNDLE_CREATE_AP=1 also installs the vendored create_ap (fetched by
# packaging/fetch-create-ap.sh) to $(LIBDIR)/hotspot-toggle/create_ap, a
# private path that never clashes with a system-wide create_ap.

NAME    := hotspot-toggle
VERSION := $(shell cat VERSION)

PREFIX  ?= /usr/local
DESTDIR ?=
BINDIR  ?= $(PREFIX)/bin
DATADIR ?= $(PREFIX)/share
LIBDIR  ?= $(PREFIX)/lib
APPDIR  ?= $(DATADIR)/$(NAME)

# Fixed system locations: polkit, GLib and sudoers-style config are looked up
# here regardless of PREFIX.
POLKIT_ACTIONS_DIR ?= /usr/share/polkit-1/actions
POLKIT_RULES_DIR   ?= /etc/polkit-1/rules.d
SCHEMA_DIR         ?= /usr/share/glib-2.0/schemas

BUNDLE_CREATE_AP ?= 0
APP_ID  := io.github.local.hotspot-toggle
HELPER  := $(BINDIR)/gnome-hotspot-helper

.PHONY: all install uninstall dist test clean distclean
all:
	@echo "Nothing to build. Run 'make install' (as root) or 'make dist'."

install:
	install -d $(DESTDIR)$(BINDIR) $(DESTDIR)$(APPDIR)
	sed 's|@APPDIR@|$(APPDIR)|g' bin/hotspot-toggle.in > $(DESTDIR)$(BINDIR)/hotspot-toggle
	chmod 755 $(DESTDIR)$(BINDIR)/hotspot-toggle
	install -m755 bin/gnome-hotspot-helper $(DESTDIR)$(HELPER)
	install -m644 hotspot_toggle_gtk.py hotspot_toggle_cli.py create_ap_helper.py $(DESTDIR)$(APPDIR)/
	# polkit: the action is pinned to the helper's exact installed path
	install -d $(DESTDIR)$(POLKIT_ACTIONS_DIR) $(DESTDIR)$(POLKIT_RULES_DIR)
	sed 's|/usr/local/bin/gnome-hotspot-helper|$(HELPER)|g' polkit/local.hotspot-toggle.policy \
		> $(DESTDIR)$(POLKIT_ACTIONS_DIR)/local.hotspot-toggle.policy
	chmod 644 $(DESTDIR)$(POLKIT_ACTIONS_DIR)/local.hotspot-toggle.policy
	install -m644 polkit/49-hotspot-toggle.rules $(DESTDIR)$(POLKIT_RULES_DIR)/49-hotspot-toggle.rules
	install -Dm644 schemas/$(APP_ID).gschema.xml $(DESTDIR)$(SCHEMA_DIR)/$(APP_ID).gschema.xml
	install -Dm644 data/$(APP_ID).desktop $(DESTDIR)$(DATADIR)/applications/$(APP_ID).desktop
	install -Dm644 data/$(APP_ID).svg $(DESTDIR)$(DATADIR)/icons/hicolor/scalable/apps/$(APP_ID).svg
	install -Dm644 data/hotspot-toggle.bash-completion $(DESTDIR)$(DATADIR)/bash-completion/completions/hotspot-toggle
	install -Dm644 data/hotspot-toggle.1 $(DESTDIR)$(DATADIR)/man/man1/hotspot-toggle.1
	install -Dm644 README.md $(DESTDIR)$(DATADIR)/doc/$(NAME)/README.md
ifeq ($(BUNDLE_CREATE_AP),1)
	@test -f vendor/create_ap/create_ap || { echo "vendor/create_ap missing: run packaging/fetch-create-ap.sh"; exit 1; }
	install -Dm755 vendor/create_ap/create_ap $(DESTDIR)$(LIBDIR)/$(NAME)/create_ap
	install -Dm644 vendor/create_ap/LICENSE $(DESTDIR)$(DATADIR)/doc/$(NAME)/create_ap.LICENSE
endif
ifeq ($(DESTDIR),)
	-glib-compile-schemas $(SCHEMA_DIR)
	-update-desktop-database $(DATADIR)/applications 2>/dev/null
	-gtk-update-icon-cache -q -t -f $(DATADIR)/icons/hicolor 2>/dev/null
endif

uninstall:
	-systemctl list-units --plain --no-legend 'gnome-hotspot-*.service' 2>/dev/null | \
		awk '{print $$1}' | xargs -r systemctl stop
	rm -f $(DESTDIR)$(BINDIR)/hotspot-toggle $(DESTDIR)$(HELPER)
	rm -rf $(DESTDIR)$(APPDIR) $(DESTDIR)$(LIBDIR)/$(NAME)
	rm -f $(DESTDIR)$(POLKIT_ACTIONS_DIR)/local.hotspot-toggle.policy
	rm -f $(DESTDIR)$(POLKIT_RULES_DIR)/49-hotspot-toggle.rules
	rm -f $(DESTDIR)$(SCHEMA_DIR)/$(APP_ID).gschema.xml
	rm -f $(DESTDIR)$(DATADIR)/applications/$(APP_ID).desktop
	rm -f $(DESTDIR)$(DATADIR)/icons/hicolor/scalable/apps/$(APP_ID).svg
	rm -f $(DESTDIR)$(DATADIR)/bash-completion/completions/hotspot-toggle
	rm -f $(DESTDIR)$(DATADIR)/man/man1/hotspot-toggle.1
	rm -rf $(DESTDIR)$(DATADIR)/doc/$(NAME)
ifeq ($(DESTDIR),)
	-glib-compile-schemas $(SCHEMA_DIR)
	-update-desktop-database $(DATADIR)/applications 2>/dev/null
endif

# Source tarball used by every package build (rpm/deb/arch/AppImage), including a
# pinned snapshot of create_ap so package builds need no network access.
dist:
	@test -f vendor/create_ap/create_ap || packaging/fetch-create-ap.sh
	mkdir -p dist
	tar --transform 's,^\.,$(NAME)-$(VERSION),' \
		--exclude=./dist --exclude=./.git --exclude=./build \
		--exclude='__pycache__' --exclude='*.pyc' --exclude=./vendor/create_ap/.git \
		-czf dist/$(NAME)-$(VERSION).tar.gz .
	@echo "==> dist/$(NAME)-$(VERSION).tar.gz"

test:
	python3 -m unittest discover -s tests -v

clean:
	rm -rf build

# Also drops dist/ and the vendored create_ap snapshot (re-fetched by `make dist`).
distclean: clean
	rm -rf dist vendor/create_ap
