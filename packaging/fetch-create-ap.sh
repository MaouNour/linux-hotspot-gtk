#!/bin/bash
# Fetch a pinned snapshot of the create_ap fork into vendor/create_ap so that
# package builds are reproducible and need no network access afterwards.
#   CREATE_AP_REF=<full commit sha>  override the pin
set -euo pipefail
cd "$(dirname "$0")/.."
REPO=${CREATE_AP_REPO:-https://github.com/MaouNour/Hotspot-Access-point-On-Linux.git}
REF=${CREATE_AP_REF:-$(cat packaging/create_ap.ref)}

rm -rf vendor/create_ap
mkdir -p vendor/create_ap
git -C vendor/create_ap init -q
git -C vendor/create_ap remote add origin "$REPO"
git -C vendor/create_ap fetch -q --depth 1 origin "$REF"
git -C vendor/create_ap checkout -q FETCH_HEAD
rm -rf vendor/create_ap/.git
echo "==> vendor/create_ap @ $REF"
