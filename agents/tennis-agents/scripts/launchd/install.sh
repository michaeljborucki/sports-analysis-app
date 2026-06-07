#!/usr/bin/env bash
# Install the two MiroFish tennis launchd agents.
#   - pipeline-tick: fires hourly, runs the pipeline for any match date in [7h, 9h] out.
#   - grade-tick:   fires daily at 04:00 America/Denver, grades strictly yesterday.
# Safe to re-run: unloads then reloads.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
AGENTS_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$AGENTS_DIR"
mkdir -p "$REPO/logs"

for label in com.mirofish.tennis-pipeline-tick com.mirofish.tennis-grade-tick; do
    src="$REPO/scripts/launchd/${label}.plist"
    dst="$AGENTS_DIR/${label}.plist"
    echo "Installing $label → $dst"
    launchctl unload "$dst" 2>/dev/null || true
    cp "$src" "$dst"
    launchctl load -w "$dst"
done

echo ""
echo "Installed. Status:"
launchctl list | grep mirofish || echo "(no mirofish jobs showing — check logs/)"
echo ""
echo "Next fire times:"
echo "  pipeline-tick: top of every hour"
echo "  grade-tick:    04:00 America/Denver daily"
echo ""
echo "Logs: $REPO/logs/"
echo "Uninstall: launchctl unload ~/Library/LaunchAgents/com.mirofish.tennis-*.plist"
