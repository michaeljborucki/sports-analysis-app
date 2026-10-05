#!/usr/bin/env bash
# Show whether both agents are loaded, their PIDs / last exit status, and
# whether the services actually answer.
DOMAIN="gui/$(id -u)"
for label in com.mike.betting-site-api com.mike.betting-site-web com.mike.betting-site-logrotate; do
  printf '%-32s ' "$label"
  if out=$(launchctl print "$DOMAIN/$label" 2>/dev/null); then
    pid=$(printf '%s' "$out" | awk -F' = ' '/^\tpid = /{print $2}')
    st=$(printf '%s' "$out" | awk -F' = ' '/last exit code/{print $2}')
    echo "loaded  pid=${pid:-none}  last_exit=${st:-n/a}"
  else
    echo "NOT LOADED"
  fi
done
echo
# /docs and / are not served by this app; /api/health is the real liveness
# endpoint. The web server 307s from / to the dashboard, which counts as up.
printf 'api  http://127.0.0.1:8000/api/health -> %s\n' \
  "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8000/api/health || echo unreachable)"
printf 'web  http://127.0.0.1:3000/           -> %s\n' \
  "$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:3000/ || echo unreachable)"
