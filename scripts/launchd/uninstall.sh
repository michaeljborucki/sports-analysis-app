#!/usr/bin/env bash
# Stop and remove the betting-site launchd agents. After this the app no
# longer starts at login; run it by hand per CLAUDE.md.
set -euo pipefail
DOMAIN="gui/$(id -u)"
for label in com.mike.betting-site-api com.mike.betting-site-web com.mike.betting-site-logrotate; do
  echo "==> removing $label"
  launchctl bootout "$DOMAIN/$label" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/$label.plist"
done
echo "done."
