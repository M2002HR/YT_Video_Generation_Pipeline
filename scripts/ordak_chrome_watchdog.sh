#!/usr/bin/env bash
# Keep Ordak's visible Chrome/CDP endpoint recoverable without polling UI tabs.
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

profile_dir="${ORDAK_CHROME_PROFILE_DIR:-/root/.config/google-chrome-ordak}"
profile_name="${ORDAK_CHROME_PROFILE_NAME:-Default}"
display="${DISPLAY:-:99}"
startup_url="${ORDAK_CHROME_STARTUP_URL:-about:blank}"

mapfile -t pids < <(pgrep -f "google-chrome.*--remote-debugging-port=9222.*${profile_dir}" || true)
if ((${#pids[@]})); then
  kill -TERM "${pids[@]}" 2>/dev/null || true
  sleep 4
fi

DISPLAY="$display" nohup /usr/bin/google-chrome \
  --no-sandbox --no-first-run --disable-background-networking \
  --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 \
  --user-data-dir="$profile_dir" --profile-directory="$profile_name" \
  "$startup_url" >>/var/log/ordak-chrome-watchdog.log 2>&1 &

printf '0\n' >"$failure_file"
