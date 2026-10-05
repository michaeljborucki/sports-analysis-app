#!/usr/bin/env bash
# Restart both agents (e.g. after a server code change).
set -euo pipefail
DOMAIN="gui/$(id -u)"
for label in com.mike.betting-site-api com.mike.betting-site-web; do
  echo "==> kickstart $label"
  launchctl kickstart -k "$DOMAIN/$label"
done
