#!/usr/bin/env bash
# Where does the page time go? Times each layer on its own, using throw-away test files
# that are removed at the end. Changes nothing else.
#
#   bash ~/nexopay3/deploy/speedtest.sh
set -euo pipefail

main() {
  APP_DIR="${APP_DIR:-$HOME/nexopay3}"
  APP_NAME="$(basename "$APP_DIR")"
  VENV="${VENV:-$(ls -d "$HOME"/virtualenv/"$APP_NAME"/3.* 2>/dev/null | sort -V | tail -1)}"
  local static_root site scheme host port
  static_root="$(grep -E '^STATIC_ROOT=' "$APP_DIR/.env" | cut -d= -f2-)"
  site="$(grep -E '^SITE_URL=' "$APP_DIR/.env" | cut -d= -f2-)"
  DOCROOT="${static_root%/static}"
  SOCK="$APP_DIR/tmp/appserver/app.sock"
  scheme="${site%%://*}"; host="${site#*://}"; host="${host%%/*}"
  port=443; [ "$scheme" = http ] && port=80

  local tag="speedtest-$RANDOM$RANDOM"
  TEST_DIR="$DOCROOT/$tag"
  TEST_CGI="$DOCROOT/cgi-bin/$tag.cgi"
  mkdir -p "$TEST_DIR" "$DOCROOT/cgi-bin"
  trap 'rm -rf "$TEST_DIR" "$TEST_CGI"' EXIT
  write_probes "$host"

  echo "Nexopay speed test - times in milliseconds, 5 tries each (first byte received)"
  echo
  echo "On this server:"
  row "Python start-up (forwarder, -S)" "$(startup_ms -S)"
  row "Python start-up (normal)" "$(startup_ms)"
  row "App server alone (home page)" "$(socket_ms "$host")"
  echo

  local ip origin=""
  for ip in 127.0.0.1 $(hostname -I 2>/dev/null || true); do
    if [ "$(curl -sk -m 10 -o /dev/null -w '%{http_code}' --resolve "$host:$port:$ip" "$site/$tag/hello.php" || true)" = 200 ]; then
      origin="$ip"; break
    fi
  done
  if [ -n "$origin" ]; then
    local direct=(--resolve "$host:$port:$origin" -k -H "X-Forwarded-Proto: $scheme")
    echo "Web server directly (skipping Cloudflare, via $origin):"
    row "Static file" "$(ttfb "$site/static/css/app.css" "${direct[@]}")"
    row "PHP hello" "$(ttfb "$site/$tag/hello.php" "${direct[@]}")"
    row "CGI hello (Python -S)" "$(ttfb "$site/cgi-bin/$tag.cgi" "${direct[@]}")"
    row "PHP -> app server" "$(ttfb "$site/$tag/relay.php" "${direct[@]}")"
    echo "    relay says: $(curl -sk -m 30 "${direct[@]}" "$site/$tag/relay.php" | head -c 200 || true)"
    row "Home page (current bridge)" "$(ttfb "$site/" "${direct[@]}")"
  else
    echo "Web server directly: couldn't reach it without Cloudflare - skipped."
  fi
  echo

  echo "Through Cloudflare (what visitors get; each try opens a new connection):"
  row "Static file" "$(ttfb "$site/static/css/app.css")"
  row "Home page" "$(ttfb "$site/")"
  echo "    one home page request: $(curl -s -m 30 -o /dev/null -w 'connect %{time_connect}s, TLS %{time_appconnect}s, first byte %{time_starttransfer}s, cf-cache: ' "$site/" || true)$(curl -s -m 30 -D - -o /dev/null "$site/" | tr -d '\r' | awk -F': ' 'tolower($1)=="cf-cache-status"{print $2}' || true)"
  echo
  bash "$APP_DIR/deploy/appserver.sh" status
}

write_probes() {
  local host="$1"
  printf '<?php echo "ok";\n' > "$TEST_DIR/hello.php"
  cat > "$TEST_DIR/relay.php" <<'PHP'
<?php
// Can PHP reach the app server's socket, and how fast is the round trip?
header('Content-Type: text/plain');
header('Cache-Control: no-store');
$t = microtime(true);
if (!function_exists('stream_socket_client')) { echo 'relay-fail: stream_socket_client is disabled'; exit; }
$s = @stream_socket_client('unix://__SOCK__', $errno, $errstr, 3);
if (!$s) { $e = error_get_last(); echo "relay-fail: $errno $errstr " . ($e ? $e['message'] : ''); exit; }
fwrite($s, "GET / HTTP/1.0\r\nHost: __HOST__\r\nX-Forwarded-Proto: https\r\nX-Nexopay-Scheme: https\r\nConnection: close\r\n\r\n");
$reply = stream_get_contents($s);
fclose($s);
printf('relay-ok: %s, %d bytes in %.0f ms', strtok($reply, "\r\n"), strlen($reply), (microtime(true) - $t) * 1000);
PHP
  sed -i "s|__SOCK__|$SOCK|; s|__HOST__|$host|" "$TEST_DIR/relay.php"
  printf '#!%s/bin/python -S\nimport sys\nsys.stdout.write("Content-Type: text/plain\\r\\n\\r\\nok")\n' "$VENV" > "$TEST_CGI"
  chmod 755 "$TEST_DIR" "$TEST_CGI"
}

row() { printf '  %-34s %s\n' "$1" "$2"; }

ttfb() {  # URL [curl args...] -> five first-byte times in ms
  local url="$1" out="" i r
  shift
  for i in 1 2 3 4 5; do
    r="$(curl -s -m 30 -o /dev/null -w '%{http_code} %{time_starttransfer}' "$@" "$url" || echo "000 0")"
    out+="$(awk '{ if ($1 != 200) printf "HTTP%s ", $1; else printf "%d ", $2 * 1000 }' <<<"$r")"
  done
  echo "$out"
}

startup_ms() {
  local out="" i s e
  for i in 1 2 3 4 5; do
    s="$(date +%s%N)"; "$VENV/bin/python" "$@" -c pass; e="$(date +%s%N)"
    out+="$(( (e - s) / 1000000 )) "
  done
  echo "$out"
}

socket_ms() {
  "$VENV/bin/python" - "$SOCK" "$1" <<'PY'
import socket
import sys
import time

path, host = sys.argv[1], sys.argv[2]
out = []
for _ in range(5):
    t = time.perf_counter()
    try:
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(30)
        s.connect(path)
        s.sendall(f"GET / HTTP/1.0\r\nHost: {host}\r\nX-Forwarded-Proto: https\r\nX-Nexopay-Scheme: https\r\n\r\n".encode())
        data = b""
        while chunk := s.recv(65536):
            data += chunk
        s.close()
    except OSError as e:
        out.append(f"not reachable ({e.__class__.__name__})")
        break
    code = data.split(b" ", 2)[1].decode() if data.count(b" ") >= 2 else "?"
    out.append(f"{(time.perf_counter() - t) * 1000:.0f}" + ("" if code == "200" else f"(HTTP{code})"))
print(" ".join(out))
PY
}

main "$@"
exit
