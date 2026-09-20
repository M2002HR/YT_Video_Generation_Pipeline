#!/usr/bin/env bash
# Keep Ordak's visible Chrome/CDP endpoint recoverable without spawning a
# competing Chrome process.  The systemd service owns the profile and already
# has Restart=always; restarting that owner preserves the authenticated profile
# while avoiding the old duplicate-process/profile-name race.
set -euo pipefail

state_dir="${ORDAK_CHROME_WATCHDOG_STATE_DIR:-/var/lib/ordak-chrome-watchdog}"
failure_file="$state_dir/consecutive_failures"
mkdir -p "$state_dir"

if curl --noproxy '*' --connect-timeout 2 --max-time 5 -fsS http://127.0.0.1:9222/json/version >/dev/null; then
  printf '0\n' >"$failure_file"
  exit 0
fi

failures=0
[[ -f "$failure_file" ]] && failures="$(cat "$failure_file")"
failures=$((failures + 1))
printf '%s\n' "$failures" >"$failure_file"

# A transient DevTools stall must not kill a healthy user session.
[[ "$failures" -lt 3 ]] && exit 0

logger -t ordak-chrome-watchdog "DevTools failed three consecutive probes; restarting ordak-chrome.service"
systemctl restart ordak-chrome.service

printf '0\n' >"$failure_file"
