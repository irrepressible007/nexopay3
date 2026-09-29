#!/usr/bin/env bash
# Always-on app server for deploy/cgi_bridge.sh's fast mode: gunicorn on a private Unix
# socket, so Python and Django stay loaded between requests.
#
#   bash ~/nexopay3/deploy/appserver.sh status
#   bash ~/nexopay3/deploy/appserver.sh start     # does nothing if already running (cron runs this every minute)
#   bash ~/nexopay3/deploy/appserver.sh reload    # load new code without dropping requests (deploy.sh does this)
#   bash ~/nexopay3/deploy/appserver.sh stop
#   bash ~/nexopay3/deploy/appserver.sh enable    # start + add the keep-alive cron line (cgi_bridge.sh fast does this)
#   bash ~/nexopay3/deploy/appserver.sh disable   # remove the cron line + stop
set -euo pipefail

main() {
  APP_DIR="${APP_DIR:-$HOME/nexopay3}"
  APP_NAME="$(basename "$APP_DIR")"
  VENV="${VENV:-$(ls -d "$HOME"/virtualenv/"$APP_NAME"/3.* 2>/dev/null | sort -V | tail -1)}"
  RUN_DIR="$APP_DIR/tmp/appserver"
  SOCK="$RUN_DIR/app.sock"
  PIDFILE="$RUN_DIR/gunicorn.pid"
  LOCK="$RUN_DIR/lock"
  LOG="$APP_DIR/logs/appserver.log"
  CRON_TAG="# nexopay-appserver"
  CRON_LINE="* * * * * bash $APP_DIR/deploy/appserver.sh start >/dev/null 2>&1 $CRON_TAG"

  mkdir -p "$RUN_DIR" "$APP_DIR/logs"
  chmod 700 "$RUN_DIR"  # the socket inside is reachable by this account only

  case "${1:-status}" in
    start) start ;;
    run) run ;;
    stop) stop ;;
    reload) reload ;;
    status) status ;;
    enable) start && cron_add ;;
    disable) cron_remove; stop ;;
    *) echo "Usage: $0 start|stop|reload|status|enable|disable" >&2; exit 1 ;;
  esac
}

# The running server holds $LOCK for its whole life, so the lock says whether it's up.
running() {
  if command -v flock >/dev/null 2>&1; then ! flock -n "$LOCK" true; else [ -n "$(master_pid)" ]; fi
}

master_pid() {
  local pid
  pid="$(cat "$PIDFILE" 2>/dev/null || true)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && echo "$pid"
}

start() {
  if running; then echo "App server: already running"; return 0; fi
  [ -x "$VENV/bin/gunicorn" ] || { echo "gunicorn is missing - run deploy/deploy.sh first." >&2; return 1; }
  # A new session, so closing the SSH window doesn't signal it.
  if command -v setsid >/dev/null 2>&1; then
    setsid bash "$APP_DIR/deploy/appserver.sh" run </dev/null >>"$LOG" 2>&1 &
  else
    nohup bash "$APP_DIR/deploy/appserver.sh" run </dev/null >>"$LOG" 2>&1 &
  fi
  local i
  for i in $(seq 1 60); do
    if [ -S "$SOCK" ] && [ -n "$(master_pid)" ]; then echo "✓ App server running"; return 0; fi
    sleep 0.5
  done
  echo "The app server did not start. Last lines of $LOG:" >&2
  tail -20 "$LOG" >&2
  return 1
}

run() {
  command -v flock >/dev/null 2>&1 || { echo "flock is not available on this server." >&2; exit 1; }
  exec 9>"$LOCK"
  flock -n 9 || exit 0  # already running
  rm -f "$SOCK"
  cd "$APP_DIR"
  exec "$VENV/bin/gunicorn" bridge_wsgi:application \
    --bind "unix:$SOCK" \
    --workers "${APP_WORKERS:-2}" --worker-class gthread --threads "${APP_THREADS:-4}" \
    --timeout 60 --graceful-timeout 30 \
    --max-requests 2000 --max-requests-jitter 200 \
    --pid "$PIDFILE" --error-logfile "$LOG" --log-level warning
}

stop() {
  local pid i
  pid="$(master_pid || true)"
  if [ -z "$pid" ]; then echo "App server: not running"; return 0; fi
  kill -TERM "$pid"  # graceful: requests in progress are finished first
  for i in $(seq 1 80); do
    running || { echo "✓ App server stopped"; return 0; }
    sleep 0.5
  done
  echo "App server still stopping (pid $pid) - check again shortly." >&2
}

reload() {
  local pid
  pid="$(master_pid || true)"
  if [ -z "$pid" ]; then echo "App server: not running (nothing to reload)"; return 0; fi
  kill -HUP "$pid"  # new workers load the new code; old ones finish their requests first
  echo "✓ App server reloading"
}

status() {
  local pid
  pid="$(master_pid || true)"
  if running && [ -n "$pid" ]; then echo "App server: running (pid $pid)"; else echo "App server: not running"; fi
  if crontab -l 2>/dev/null | grep -qF "$CRON_TAG"; then echo "Keep-alive cron: on"; else echo "Keep-alive cron: off"; fi
}

# Edit only our own tagged line; everything else in the crontab is kept as it is.
cron_read() {
  local out
  if out="$(crontab -l 2>&1)"; then printf '%s\n' "$out"; return 0; fi
  case "$out" in *"no crontab"*) return 0 ;; esac
  return 1
}

cron_add() {
  local current
  if ! current="$(cron_read)"; then
    echo "Couldn't read your crontab. Add this line in cPanel > Cron Jobs:" >&2
    echo "  ${CRON_LINE% $CRON_TAG}" >&2
    return 0
  fi
  if printf '%s\n' "$current" | grep -qxF "$CRON_LINE"; then echo "Keep-alive cron: already on"; return 0; fi
  { [ -n "$current" ] && printf '%s\n' "$current" | grep -vF "$CRON_TAG" || true; echo "$CRON_LINE"; } | crontab -
  echo "✓ Keep-alive cron added (restarts the app server within a minute if it ever stops)"
}

cron_remove() {
  local current
  current="$(cron_read)" || return 0
  printf '%s\n' "$current" | grep -qF "$CRON_TAG" || return 0
  { printf '%s\n' "$current" | grep -vF "$CRON_TAG" || true; } | crontab -
  echo "✓ Keep-alive cron removed"
}

main "$@"
exit
