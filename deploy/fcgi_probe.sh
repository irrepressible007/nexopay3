#!/usr/bin/env bash
# Can this server keep Python running between requests (FastCGI)? Safe test: puts a
# tiny throw-away page in its own folder, requests it 3 times, then removes it.
# Run it with the CGI bridge ON (so the Python app is stopped):
#
#   bash ~/nexopay3/deploy/fcgi_probe.sh
set -euo pipefail

main() {
  APP_DIR="${APP_DIR:-$HOME/nexopay3}"
  APP_NAME="$(basename "$APP_DIR")"
  VENV="${VENV:-$(ls -d "$HOME"/virtualenv/"$APP_NAME"/3.* 2>/dev/null | sort -V | tail -1)}"
  local static_root site
  static_root="$(grep -E '^STATIC_ROOT=' "$APP_DIR/.env" | cut -d= -f2-)"
  site="$(grep -E '^SITE_URL=' "$APP_DIR/.env" | cut -d= -f2-)"
  PROBE="${static_root%/static}/fcgi-probe"

  echo "Installing the FastCGI library (flup) into the app's environment..."
  "$VENV/bin/pip" install --quiet --disable-pip-version-check "flup==1.0.3"

  mkdir -p "$PROBE"
  trap 'rm -rf "$PROBE"' EXIT
  cat > "$PROBE/probe.fcgi" <<PY
#!$VENV/bin/python
import os
from flup.server.fcgi_single import WSGIServer


def app(environ, start_response):
    start_response("200 OK", [("Content-Type", "text/plain"), ("Cache-Control", "no-store")])
    return [("probe-ok pid=%s" % os.getpid()).encode()]


WSGIServer(app).run()
PY
  # Same folder setup the bridge's fast mode uses.
  printf 'Options +ExecCGI -Indexes\nAddHandler fcgid-script .fcgi\n' > "$PROBE/.htaccess"
  chmod 755 "$PROBE" "$PROBE/probe.fcgi"

  local r1 r2 r3
  r1="$(fetch "$site/fcgi-probe/probe.fcgi?1")"
  r2="$(fetch "$site/fcgi-probe/probe.fcgi?2")"
  r3="$(fetch "$site/fcgi-probe/probe.fcgi?3")"
  echo "request 1: ${r1:0:100}"
  echo "request 2: ${r2:0:100}"
  echo "request 3: ${r3:0:100}"

  if [[ "$r1" == probe-ok* && "$r2" == probe-ok* && "$r3" == probe-ok* ]]; then
    if [ "$(pid_of "$r1")" = "$(pid_of "$r2")" ] || [ "$(pid_of "$r2")" = "$(pid_of "$r3")" ]; then
      echo "RESULT: FAST MODE SUPPORTED ✓ (Python stayed running between requests)"
    else
      echo "RESULT: runs, but Python restarts on every request (no speed gain) - stay on the CGI bridge"
    fi
  elif [[ "$r1" == *WSGIServer* ]]; then
    echo "RESULT: NOT supported (the server showed the file instead of running it)"
  else
    echo "RESULT: NOT supported (error or timeout) - stay on the CGI bridge"
  fi
}

fetch() {
  curl -s -m 25 -w ' [HTTP %{http_code}]' "$1" | tr -d '\r' | tr '\n' ' ' || true
}

pid_of() {
  local rest="${1#*pid=}"
  echo "${rest%% *}"
}

main "$@"
exit
