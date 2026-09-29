#!/usr/bin/env bash
# Install Nexopay's scheduled jobs (deploy/crontab.txt) into this account's crontab.
# Only lines tagged "# nexopay-cron" are touched; everything else in the crontab is kept.
#
#   bash ~/nexopay3/deploy/cron.sh install   # add the jobs, or update them after crontab.txt changes
#   bash ~/nexopay3/deploy/cron.sh remove
#   bash ~/nexopay3/deploy/cron.sh status
set -euo pipefail

main() {
  APP_DIR="${APP_DIR:-$HOME/nexopay3}"
  TAG="# nexopay-cron"
  case "${1:-status}" in
    install) install ;;
    remove) remove ;;
    status) status ;;
    *) echo "Usage: $0 install|remove|status" >&2; exit 1 ;;
  esac
}

jobs() {
  grep -vE '^[[:space:]]*(#|$)' "$APP_DIR/deploy/crontab.txt" | sed "s|\$| $TAG|"
}

# Returns the current crontab; fails (so nothing gets overwritten) if it can't be read.
cron_read() {
  local out
  if out="$(crontab -l 2>&1)"; then printf '%s\n' "$out"; return 0; fi
  case "$out" in *"no crontab"*) return 0 ;; esac
  echo "Couldn't read your crontab: $out" >&2
  return 1
}

install() {
  local current
  current="$(cron_read)"
  mkdir -p "$APP_DIR/logs"
  { [ -n "$current" ] && printf '%s\n' "$current" | grep -vF "$TAG" || true; jobs; } | crontab -
  echo "✓ Scheduled jobs installed ($(jobs | wc -l) lines):"
  status
}

remove() {
  local current
  current="$(cron_read)"
  printf '%s\n' "$current" | grep -qF "$TAG" || { echo "No Nexopay scheduled jobs installed."; return 0; }
  { printf '%s\n' "$current" | grep -vF "$TAG" || true; } | crontab -
  echo "✓ Scheduled jobs removed"
}

status() {
  crontab -l 2>/dev/null | grep -F "$TAG" | sed 's/^/  /' || echo "  (none installed)"
  if [ -f "$APP_DIR/logs/cron.log" ]; then
    echo "Last lines of logs/cron.log:"
    tail -5 "$APP_DIR/logs/cron.log" | sed 's/^/  /'
  fi
}

main "$@"
exit
