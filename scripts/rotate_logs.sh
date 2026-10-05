#!/usr/bin/env bash
# Rotate the betting-site logs in logs/ so they stop eating the disk.
#
# The API agent logs every APScheduler tick and every coral33 normalizer
# result to stderr, which ran launchd-api.err.log to 300 MB in five days.
#
# COPY-TRUNCATE, not move-and-recreate: launchd opened these files and holds
# the descriptors for the life of the agent. Renaming the file leaves the
# running server writing into the rotated inode, so the "current" log stays
# empty until the next restart. Copying the contents aside and then
# truncating in place keeps the descriptor pointing at the same inode.
#
# Run by com.mike.betting-site-logrotate every hour; safe to run by hand.
set -euo pipefail

LOGS="/Users/mikeborucki/personal_workspace/betting-site/logs"
MAX_BYTES=$((50 * 1024 * 1024))   # rotate once a log passes 50 MB
KEEP=3                            # .1.gz .2.gz .3.gz

cd "$LOGS" || exit 0

for log in *.log *.err *.out; do
  [ -f "$log" ] || continue

  size=$(stat -f%z "$log")
  [ "$size" -gt "$MAX_BYTES" ] || continue

  echo "$(date '+%Y-%m-%d %H:%M:%S') rotating $log ($((size / 1024 / 1024)) MB)"

  # Age the existing generations; the oldest falls off the end.
  rm -f "$log.$KEEP.gz"
  for i in $(seq $((KEEP - 1)) -1 1); do
    [ -f "$log.$i.gz" ] && mv "$log.$i.gz" "$log.$((i + 1)).gz"
  done

  cp "$log" "$log.1"
  : > "$log"
  gzip -f "$log.1"
done
