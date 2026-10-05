#!/usr/bin/env bash
# The web launch agent serves the prebuilt web/.next bundle, so changes to
# web/ code are invisible until you rebuild. This does the build and
# restarts only the web agent (the API keeps serving throughout).
set -euo pipefail
REPO="/Users/mikeborucki/personal_workspace/betting-site"
cd "$REPO/web"
/opt/homebrew/bin/npm run build
launchctl kickstart -k "gui/$(id -u)/com.mike.betting-site-web"
echo "==> web rebuilt and restarted on :3000"
