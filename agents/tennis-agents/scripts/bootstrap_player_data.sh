#!/usr/bin/env bash
# Bootstrap the local Sackmann archive from Jeff Sackmann's GitHub repos.
#
# Runs once on a fresh clone. Downloads the 2020-2024 match CSVs + players
# + current rankings for ATP and WTA into data/sackmann/{atp,wta}/.
#
# Idempotent: if data/sackmann/{atp,wta}/atp_matches_2024.csv and
# wta_matches_2024.csv already exist, exits immediately.
#
# After bootstrap, run scripts/backfill_player_data.py to populate 2025+
# matches from api-tennis.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$REPO/data/sackmann"

ATP_BASE="https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master"
WTA_BASE="https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master"

# If both 2024 files are already present, we're bootstrapped.
if [[ -f "$DEST/atp/atp_matches_2024.csv" && -f "$DEST/wta/wta_matches_2024.csv" ]]; then
  echo "Bootstrap: already populated ($DEST). Nothing to do."
  exit 0
fi

mkdir -p "$DEST/atp" "$DEST/wta"

fetch() {
  local url="$1"
  local out="$2"
  echo "  Fetching $(basename "$out")..."
  if ! curl -fsSL --retry 3 --retry-delay 2 -o "$out" "$url"; then
    echo "  FAIL: could not fetch $url" >&2
    return 1
  fi
}

echo "Bootstrapping local Sackmann archive into $DEST"
echo ""
echo "[ATP]"
for year in 2020 2021 2022 2023 2024; do
  fetch "$ATP_BASE/atp_matches_${year}.csv" "$DEST/atp/atp_matches_${year}.csv"
done
fetch "$ATP_BASE/atp_players.csv" "$DEST/atp/atp_players.csv"
fetch "$ATP_BASE/atp_rankings_current.csv" "$DEST/atp/atp_rankings_current.csv"

echo ""
echo "[WTA]"
for year in 2020 2021 2022 2023 2024; do
  fetch "$WTA_BASE/wta_matches_${year}.csv" "$DEST/wta/wta_matches_${year}.csv"
done
fetch "$WTA_BASE/wta_players.csv" "$DEST/wta/wta_players.csv"
fetch "$WTA_BASE/wta_rankings_current.csv" "$DEST/wta/wta_rankings_current.csv"

echo ""
echo "Bootstrap complete. Next: python3 scripts/backfill_player_data.py --start 2025-01-01"
