#!/usr/bin/env bash
# Install (or reinstall) the betting-site launchd agents so the FastAPI
# backend (:8000) and the Next.js production server (:3000) start
# automatically at login and stay up.
#
# The plists in this directory are the source of truth; this script copies
# them into ~/Library/LaunchAgents and (re)bootstraps them. Re-run it after
# editing a plist.
set -euo pipefail

REPO="/Users/mikeborucki/personal_workspace/betting-site"
AGENTS="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"
LABELS=(com.mike.betting-site-api com.mike.betting-site-web com.mike.betting-site-logrotate)

mkdir -p "$AGENTS" "$REPO/logs"

# Free the ports if a hand-started dev instance is holding them, otherwise
# the agents crash-loop on "address already in use".
if lsof -ti:8000,3000 >/dev/null 2>&1; then
  echo "==> stopping processes already on :8000/:3000"
  lsof -ti:8000,3000 | xargs kill 2>/dev/null || true
  sleep 2
fi

# Build the web bundle: the web agent serves web/.next and never builds.
echo "==> building web (next build)"
(cd "$REPO/web" && /opt/homebrew/bin/npm run build)

for label in "${LABELS[@]}"; do
  echo "==> installing $label"
  # bootout returns before launchd has finished tearing the job down; a
  # bootstrap issued into that window fails with "5: Input/output error".
  # Poll until the label is genuinely gone (cap ~15s) before re-bootstrapping.
  launchctl bootout "$DOMAIN/$label" 2>/dev/null || true
  for _ in $(seq 30); do
    launchctl print "$DOMAIN/$label" >/dev/null 2>&1 || break
    sleep 0.5
  done
  cp "$REPO/scripts/launchd/$label.plist" "$AGENTS/$label.plist"
  launchctl bootstrap "$DOMAIN" "$AGENTS/$label.plist"
  launchctl enable "$DOMAIN/$label"
done

echo
echo "==> installed. status:"
"$REPO/scripts/launchd/status.sh"
