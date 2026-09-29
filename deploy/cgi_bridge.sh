#!/usr/bin/env bash
# Serve Nexopay on hosts whose LiteSpeed lacks the Python connector (lswsgi),
# so cPanel's "Setup Python App" cannot start the app.
#
#   bash ~/nexopay3/deploy/cgi_bridge.sh fast     # forwarder + always-on app server (deploy/appserver.sh)
#   bash ~/nexopay3/deploy/cgi_bridge.sh on       # plain CGI: Django loads on every request (~1 s per page)
#   bash ~/nexopay3/deploy/cgi_bridge.sh off      # remove the bridge (then "Start app" in cPanel)
#   bash ~/nexopay3/deploy/cgi_bridge.sh status
#
# Fast mode forwards through PHP when the server allows it (PHP stays loaded, so that adds only
# milliseconds) - it tests this first - and otherwise through a small CGI script. If the app
# server is ever down, pages are served the slow CGI way instead of failing.
# Every mode needs the Python app STOPPED in cPanel (Setup Python App > Stop app).
set -euo pipefail

main() {
  local action="${1:-status}"
  APP_DIR="${APP_DIR:-$HOME/nexopay3}"
  APP_NAME="$(basename "$APP_DIR")"
  VENV="${VENV:-$(ls -d "$HOME"/virtualenv/"$APP_NAME"/3.* 2>/dev/null | sort -V | tail -1)}"
  local static_root
  static_root="$(grep -E '^STATIC_ROOT=' "$APP_DIR/.env" | cut -d= -f2- || true)"
  SITE="$(grep -E '^SITE_URL=' "$APP_DIR/.env" | cut -d= -f2- || true)"
  DOCROOT="${DOCROOT:-${static_root%/static}}"
  HTACCESS="$DOCROOT/.htaccess"
  CGI_SCRIPT="$DOCROOT/cgi-bin/nexopay.cgi"
  PHP_BRIDGE="$DOCROOT/nexopay-bridge.php"
  SOCK="$APP_DIR/tmp/appserver/app.sock"
  APPSERVER="$APP_DIR/deploy/appserver.sh"
  BEGIN="# BEGIN NEXOPAY CGI BRIDGE"
  END="# END NEXOPAY CGI BRIDGE"

  [ -n "$DOCROOT" ] && [ -d "$DOCROOT" ] || { echo "Document root not found (check STATIC_ROOT in $APP_DIR/.env)." >&2; exit 1; }
  [ -x "$VENV/bin/python" ] || { echo "Virtualenv not found at $VENV." >&2; exit 1; }

  case "$action" in
    on | cgi)
      require_app_stopped
      write_cgi direct
      write_block cgi
      rm -f "$PHP_BRIDGE"
      bash "$APPSERVER" disable
      echo "✓ Bridge ON (CGI) for $DOCROOT"
      ;;
    fast)
      require_app_stopped
      "$VENV/bin/pip" install --quiet --disable-pip-version-check \
        "$(grep -E '^gunicorn' "$APP_DIR/requirements.txt" | cut -d' ' -f1)"
      bash "$APPSERVER" enable
      if enable_php; then
        echo "✓ Bridge FAST (PHP forwarder) for $DOCROOT"
      else
        write_cgi forward
        write_block cgi
        rm -f "$PHP_BRIDGE"
        echo "✓ Bridge FAST (CGI forwarder) for $DOCROOT"
      fi
      ;;
    off)
      strip_block
      rm -f "$CGI_SCRIPT" "$PHP_BRIDGE"
      bash "$APPSERVER" disable
      echo "✓ Bridge OFF. To use the normal Python app: cPanel > Setup Python App > 'Start app'."
      ;;
    status)
      if ! grep -qF "$BEGIN" "$HTACCESS" 2>/dev/null; then echo "Bridge: off"
      elif grep -qF "nexopay-bridge.php" "$HTACCESS"; then echo "Bridge: FAST (PHP forwarder + app server)"
      elif grep -qxF "FORWARD = True" "$CGI_SCRIPT" 2>/dev/null; then echo "Bridge: FAST (CGI forwarder + app server)"
      else echo "Bridge: ON (CGI)"; fi
      if grep -qE '^\s*PassengerAppRoot' "$HTACCESS" 2>/dev/null; then echo "Python app: running"; else echo "Python app: stopped"; fi
      bash "$APPSERVER" status
      ;;
    *) echo "Usage: $0 fast|on|off|status" >&2; exit 1 ;;
  esac
}

require_app_stopped() {
  if grep -qE '^\s*PassengerAppRoot' "$HTACCESS" 2>/dev/null; then
    echo "The Python app is still running for this domain."
    echo "First: cPanel > Setup Python App > your app > 'Stop app' (NOT Destroy, NOT Save). Then run this again."
    exit 1
  fi
}

# --- PHP forwarder -------------------------------------------------------------------------

enable_php() {
  local problem
  if ! problem="$(php_upload_check)"; then
    echo "PHP can't pass uploads on unchanged here ($problem) - using the CGI forwarder instead."
    return 1
  fi
  # A fresh secret the PHP forwarder shows the CGI fallback, so nobody else can use that script.
  BRIDGE_KEY="$(od -An -tx1 -N16 /dev/urandom | tr -d ' \n')"
  write_cgi fallback  # used by the PHP forwarder only while the app server is down
  write_php > "$PHP_BRIDGE.new"
  chmod 644 "$PHP_BRIDGE.new"
  mv -f "$PHP_BRIDGE.new" "$PHP_BRIDGE"
  write_block php
  if ! problem="$(site_check)"; then
    echo "The PHP forwarder didn't pass its check ($problem) - using the CGI forwarder instead."
    return 1
  fi
}

# Requests from this server go straight to the web server, skipping Cloudflare, when possible.
origin_args() {
  local scheme="${SITE%%://*}" host="${SITE#*://}" port=443 ip
  host="${host%%/*}"
  [ "$scheme" = http ] && port=80
  for ip in 127.0.0.1 $(hostname -I 2>/dev/null || true); do
    if [ "$(curl -sk -m 10 -o /dev/null -w '%{http_code}' --resolve "$host:$port:$ip" "$SITE/static/css/app.css" || true)" = 200 ]; then
      echo "--resolve $host:$port:$ip -k"
      return
    fi
  done
}

# Before switching: can PHP read a 6 MB upload untouched (the forwarder needs the raw body)?
php_upload_check() {
  local dir="$DOCROOT/nexopay-check-$RANDOM$RANDOM" payload="$APP_DIR/tmp/upload-check.bin" args got
  mkdir -p "$dir"
  php_flags > "$dir/.htaccess"
  printf '<?php echo strlen(file_get_contents("php://input")) . ":" . ($_SERVER["CONTENT_LENGTH"] ?? "");\n' > "$dir/check.php"
  chmod 755 "$dir"
  head -c 6000000 /dev/urandom > "$payload"
  # shellcheck disable=SC2046
  args=($(origin_args))
  got="$(curl -s -m 60 ${args[@]+"${args[@]}"} -F "file=@$payload" "$SITE/$(basename "$dir")/check.php" || true)"
  rm -rf "$dir" "$payload"
  if [[ "$got" =~ ^([0-9]+):([0-9]+)$ ]] && [ "${BASH_REMATCH[1]}" = "${BASH_REMATCH[2]}" ] && [ "${BASH_REMATCH[1]}" -gt 6000000 ]; then
    return 0
  fi
  echo "upload test gave: ${got:0:120}"
  return 1
}

# After switching: pages, a form post and a static file must work through the forwarder.
site_check() {
  local args code static
  # shellcheck disable=SC2046
  args=($(origin_args))
  for path in / /bn/; do
    code="$(curl -s -m 60 ${args[@]+"${args[@]}"} -o "$APP_DIR/tmp/site-check.html" -w '%{http_code}' "$SITE$path" || true)"
    if [ "$code" != 200 ] || ! grep -q "</html>" "$APP_DIR/tmp/site-check.html"; then
      echo "GET $path gave HTTP $code"; return 1
    fi
  done
  # A form post without a CSRF token must reach Django and be refused by it (403).
  code="$(curl -s -m 60 ${args[@]+"${args[@]}"} -o /dev/null -w '%{http_code}' -F "field=value" "$SITE/" || true)"
  [ "$code" = 403 ] || { echo "a form post gave HTTP $code instead of Django's 403"; return 1; }
  static="$(cd "$DOCROOT" && ls static/css/app.*.css 2>/dev/null | head -1 || true)"
  if [ -n "$static" ]; then
    code="$(curl -s -m 60 ${args[@]+"${args[@]}"} -o /dev/null -w '%{http_code}' "$SITE/$static" || true)"
    [ "$code" = 200 ] || { echo "the stylesheet gave HTTP $code"; return 1; }
  fi
  rm -f "$APP_DIR/tmp/site-check.html"
}

# PHP must leave upload bodies unread, so the forwarder can pass them on as they are.
php_flags() {
  local module
  for module in Litespeed lsapi_module php_module; do
    printf '<IfModule %s>\nphp_flag enable_post_data_reading off\n</IfModule>\n' "$module"
  done
}

write_php() {
  sed "s#__APP_SOCKET__#$SOCK#; s#__BRIDGE_KEY__#$BRIDGE_KEY#" <<'PHP'
<?php
// Nexopay bridge - generated by deploy/cgi_bridge.sh, do not edit.
// Relays each request to the always-on app server (deploy/appserver.sh) over its private socket.
// PHP stays loaded on this server, so this adds only milliseconds. If the app server is down,
// the request goes to the CGI script instead: slow, but never an error.

const APP_SOCKET = '__APP_SOCKET__';
const FALLBACK_SCRIPT = '/cgi-bin/nexopay.cgi';
const BRIDGE_KEY = '__BRIDGE_KEY__';  // shown to the CGI fallback, which refuses anyone without it
const SKIP_REQUEST_HEADERS = ['HTTP_CONNECTION', 'HTTP_KEEP_ALIVE', 'HTTP_PROXY_CONNECTION', 'HTTP_TE',
    'HTTP_TRAILER', 'HTTP_TRANSFER_ENCODING', 'HTTP_UPGRADE', 'HTTP_PROXY', 'HTTP_CONTENT_LENGTH',
    'HTTP_CONTENT_TYPE'];
// Hop-by-hop headers, ones the web server adds itself, and the length (the web server may compress).
const DROP_RESPONSE_HEADERS = ['connection', 'keep-alive', 'proxy-connection', 'te', 'trailer',
    'transfer-encoding', 'upgrade', 'server', 'date', 'content-length'];

function nx_https(): bool
{
    $https = strtolower((string)($_SERVER['HTTPS'] ?? ''));
    return ($https !== '' && $https !== 'off') || ($_SERVER['REQUEST_SCHEME'] ?? '') === 'https';
}

function nx_request_head(string $target, bool $toFallback = false): string
{
    $lines = [($_SERVER['REQUEST_METHOD'] ?? 'GET') . " $target HTTP/1.0"];
    foreach ($_SERVER as $key => $value) {
        if (is_string($value) && strncmp((string)$key, 'HTTP_', 5) === 0
            && strncmp((string)$key, 'HTTP_X_NEXOPAY_', 15) !== 0 && !in_array($key, SKIP_REQUEST_HEADERS, true)) {
            $lines[] = str_replace('_', '-', substr((string)$key, 5)) . ': ' . $value;
        }
    }
    if (!empty($_SERVER['CONTENT_TYPE'])) {
        $lines[] = 'Content-Type: ' . $_SERVER['CONTENT_TYPE'];
    }
    $length = (int)($_SERVER['CONTENT_LENGTH'] ?? 0);
    if ($length > 0) {
        $lines[] = "Content-Length: $length";
    }
    $lines[] = 'X-Nexopay-Remote-Addr: ' . ($_SERVER['REMOTE_ADDR'] ?? '');
    $lines[] = 'X-Nexopay-Scheme: ' . (nx_https() ? 'https' : 'http');
    if ($toFallback) {
        $lines[] = 'X-Nexopay-Bridge-Key: ' . BRIDGE_KEY;
    }
    $lines[] = 'Connection: close';
    return implode("\r\n", $lines) . "\r\n\r\n";
}

function nx_write($conn, string $data): void
{
    while ($data !== '') {
        $written = fwrite($conn, $data);
        if ($written === false || $written === 0) {
            throw new RuntimeException('could not send the request');
        }
        $data = (string)substr($data, $written);
    }
}

function nx_send_body($conn): void
{
    $length = (int)($_SERVER['CONTENT_LENGTH'] ?? 0);
    if ($length <= 0) {
        return;
    }
    $input = fopen('php://input', 'rb');
    $sent = stream_copy_to_stream($input, $conn, $length);
    fclose($input);
    if ($sent !== $length) {
        throw new RuntimeException("request body incomplete ($sent of $length bytes)");
    }
}

/** Passes the app's reply on to the visitor; false if there was no reply (nothing sent yet). */
function nx_relay($conn): bool
{
    stream_set_timeout($conn, 120);
    $status = fgets($conn);
    if ($status === false || strncmp($status, 'HTTP/', 5) !== 0) {
        return false;
    }
    $parts = explode(' ', trim($status), 3);
    $headers = [];
    while (($line = fgets($conn)) !== false) {
        $line = rtrim($line, "\r\n");
        if ($line === '') {
            break;
        }
        $name = strtolower(trim((string)strstr($line, ':', true)));
        if ($name !== '' && !in_array($name, DROP_RESPONSE_HEADERS, true)) {
            $headers[] = $line;
        }
    }
    http_response_code((int)($parts[1] ?? 502));  // first: a Location header would otherwise force 302
    foreach ($headers as $header) {
        header($header, false);
    }
    while (!feof($conn)) {
        $chunk = fread($conn, 65536);
        if ($chunk === false || ($chunk === '' && stream_get_meta_data($conn)['timed_out'])) {
            break;
        }
        echo $chunk;
        flush();
    }
    return true;
}

function nx_attempt($conn, string $target, bool $toFallback = false): bool
{
    try {
        nx_write($conn, nx_request_head($target, $toFallback));
        nx_send_body($conn);
        return nx_relay($conn);
    } catch (Throwable $e) {
        return headers_sent();  // a reply had already started: never send a second one
    } finally {
        fclose($conn);
    }
}

/** A connection to this same web server, to reach the CGI script. */
function nx_fallback_connection()
{
    $https = nx_https();
    $addr = (string)($_SERVER['SERVER_ADDR'] ?? '127.0.0.1');
    if (strpos($addr, ':') !== false) {
        $addr = "[$addr]";
    }
    $port = (int)($_SERVER['SERVER_PORT'] ?? ($https ? 443 : 80));
    $host = (string)preg_replace('/:\d+$/', '', (string)($_SERVER['HTTP_HOST'] ?? 'localhost'));
    $context = stream_context_create(['ssl' => [
        'verify_peer' => false, 'verify_peer_name' => false, 'peer_name' => $host, 'SNI_enabled' => true,
    ]]);
    return @stream_socket_client(($https ? 'tls' : 'tcp') . "://$addr:$port", $errno, $errstr, 5,
        STREAM_CLIENT_CONNECT, $context);
}

ini_set('zlib.output_compression', '0');
ini_set('default_mimetype', '');
header_remove('X-Powered-By');
@set_time_limit(300);
while (ob_get_level() > 0) {
    ob_end_clean();
}

$uri = (string)($_SERVER['REQUEST_URI'] ?? '/');
$conn = @stream_socket_client('unix://' . APP_SOCKET, $errno, $errstr, 3);
if ($conn !== false && nx_attempt($conn, $uri)) {
    exit;
}
// App server down, or no reply to a request that is safe to repeat: use the CGI script.
if ($conn === false || in_array($_SERVER['REQUEST_METHOD'] ?? 'GET', ['GET', 'HEAD'], true)) {
    $fallback = nx_fallback_connection();
    if ($fallback !== false && nx_attempt($fallback, FALLBACK_SCRIPT . $uri, true)) {
        exit;
    }
}
http_response_code(503);
header('Content-Type: text/plain; charset=utf-8');
header('Retry-After: 5');
echo "The site is restarting. Please try again in a moment.\n";
PHP
}

# --- .htaccess -----------------------------------------------------------------------------

write_block() {
  local mode="$1" target="/cgi-bin/nexopay.cgi/\$1 [L,QSA]"
  [ "$mode" = php ] && target="/nexopay-bridge.php [L]"
  if grep -qF "$BEGIN" "$HTACCESS" 2>/dev/null; then
    strip_block
  elif [ -f "$HTACCESS" ]; then
    cp -p "$HTACCESS" "$HTACCESS.before-bridge"
  fi
  {
    echo "$BEGIN"
    [ "$mode" = php ] && php_flags
    cat <<HT
<IfModule mod_rewrite.c>
RewriteEngine On
RewriteCond %{REQUEST_FILENAME} !-f
RewriteCond %{REQUEST_URI} !^/cgi-bin/
RewriteRule ^(.*)\$ $target
</IfModule>
# Collected static files with a content hash in the name never change: let browsers keep them.
<IfModule mod_headers.c>
<FilesMatch "\.[0-9a-f]{12}\.[A-Za-z0-9]+\$">
Header set Cache-Control "public, max-age=31536000, immutable"
</FilesMatch>
</IfModule>
$END
HT
  } >> "$HTACCESS"
}

strip_block() {
  [ -f "$HTACCESS" ] || return 0
  local tmp="$HTACCESS.tmp.$$"
  awk -v b="$BEGIN" -v e="$END" '$0==b{skip=1} !skip{print} $0==e{skip=0}' "$HTACCESS" > "$tmp"
  cat "$tmp" > "$HTACCESS"
  rm -f "$tmp"
}

# --- CGI script ----------------------------------------------------------------------------
# direct:   loads Django for every request (slow)
# forward:  relays to the app server; loads Django itself only while that is down
# fallback: the PHP forwarder's fallback. Like forward, but loads Django itself only for that
#           forwarder (it shows the shared key): anyone else calling it gets forwarded or a 503.

write_cgi() {
  local mode="$1" forward=True php_fallback=False flags=" -S"
  case "$mode" in
    direct) forward=False; flags="" ;;
    fallback) php_fallback=True ;;
  esac
  mkdir -p "$(dirname "$CGI_SCRIPT")"
  {
    cat <<PY
#!$VENV/bin/python$flags
# Nexopay entry point ($mode) - generated by deploy/cgi_bridge.sh, do not edit.
# -S (forward/fallback) skips loading site-packages at start-up: forwarding needs only the standard library.
import os
import socket
import sys

APP_DIR = "$APP_DIR"
APP_SOCKET = "$SOCK"
FORWARD = $forward
PHP_FALLBACK = $php_fallback
BRIDGE_KEY = "${BRIDGE_KEY:-}"
PY
    cat <<'PY'

# Hop-by-hop headers, plus ones the web server adds itself.
DROP_HEADERS = {b"connection", b"keep-alive", b"proxy-connection", b"te", b"trailer", b"transfer-encoding",
                b"upgrade", b"server", b"date"}
SKIP_ENV = {b"HTTP_CONNECTION", b"HTTP_KEEP_ALIVE", b"HTTP_PROXY_CONNECTION", b"HTTP_TE", b"HTTP_TRAILER",
            b"HTTP_TRANSFER_ENCODING", b"HTTP_UPGRADE", b"HTTP_PROXY", b"HTTP_CONTENT_LENGTH", b"HTTP_CONTENT_TYPE"}


_php_caller = None


def called_by_php_forwarder():
    """True only for this site's PHP forwarder, which proves it with the shared key."""
    global _php_caller
    if _php_caller is None:
        import hmac

        given = os.environb.get(b"HTTP_X_NEXOPAY_BRIDGE_KEY", b"")
        _php_caller = bool(BRIDGE_KEY) and hmac.compare_digest(given, BRIDGE_KEY.encode())
    return _php_caller


def visitor():
    """The visitor's address and scheme - passed on by the PHP forwarder when it is the caller."""
    env = os.environ
    https = env.get("HTTPS", "").lower() in ("on", "1") or env.get("REQUEST_SCHEME") == "https"
    addr, scheme = env.get("REMOTE_ADDR", ""), "https" if https else "http"
    if called_by_php_forwarder():
        addr = env.get("HTTP_X_NEXOPAY_REMOTE_ADDR") or addr
        scheme = env.get("HTTP_X_NEXOPAY_SCHEME") or scheme
    return addr, scheme


def run_directly():
    """Load Django in this process and answer the request (slow, but needs nothing else)."""
    if sys.flags.no_site:
        # Started with -S: restart normally so site-packages load as usual.
        # The request body is still unread and the environment is kept, so nothing is lost.
        os.environ["NEXOPAY_BRIDGE_DIRECT"] = "1"
        os.execv(sys.executable, [sys.executable, os.path.abspath(sys.argv[0])])
    sys.path.insert(0, APP_DIR)
    from wsgiref.handlers import CGIHandler

    from passenger_wsgi import application as django_app  # logs start-up errors

    addr, scheme = visitor()

    def application(environ, start_response):
        # The site lives at /, not under the bridge script's URL.
        environ["SCRIPT_NAME"] = ""
        environ.pop("SCRIPT_URL", None)
        environ.pop("REDIRECT_URL", None)
        for key in [k for k in environ if k.startswith("HTTP_X_NEXOPAY_")]:
            del environ[key]
        environ["REMOTE_ADDR"] = addr
        if scheme in ("http", "https"):
            environ["wsgi.url_scheme"] = scheme
        return django_app(environ, start_response)

    CGIHandler().run(application)


def request_head(env):
    uri = env.get(b"REQUEST_URI") or env.get(b"PATH_INFO", b"/") + (
        b"?" + env[b"QUERY_STRING"] if env.get(b"QUERY_STRING") else b"")
    if uri.startswith(b"/cgi-bin/nexopay.cgi/"):  # called by the PHP forwarder
        uri = uri[len(b"/cgi-bin/nexopay.cgi"):]
    lines = [env.get(b"REQUEST_METHOD", b"GET") + b" " + uri + b" HTTP/1.0"]
    for key, value in env.items():
        if key.startswith(b"HTTP_") and key not in SKIP_ENV and not key.startswith(b"HTTP_X_NEXOPAY_"):
            lines.append(key[5:].replace(b"_", b"-") + b": " + value)
    if env.get(b"CONTENT_TYPE"):
        lines.append(b"Content-Type: " + env[b"CONTENT_TYPE"])
    if env.get(b"CONTENT_LENGTH"):
        lines.append(b"Content-Length: " + env[b"CONTENT_LENGTH"])
    addr, scheme = visitor()
    lines.append(b"X-Nexopay-Remote-Addr: " + os.fsencode(addr))
    lines.append(b"X-Nexopay-Scheme: " + os.fsencode(scheme))
    lines.append(b"Connection: close")
    return b"\r\n".join(lines) + b"\r\n\r\n"


def forward(conn):
    """Relay this CGI request to the app server; True once a response has been sent."""
    env = os.environb
    conn.sendall(request_head(env))
    remaining = int(env.get(b"CONTENT_LENGTH") or 0)
    while remaining > 0:
        chunk = sys.stdin.buffer.read(min(remaining, 65536))
        if not chunk:
            break
        conn.sendall(chunk)
        remaining -= len(chunk)

    reply = conn.makefile("rb")
    status = reply.readline()
    if not status.startswith(b"HTTP/"):
        return False
    head = [b"Status: " + (status.split(b" ", 1)[1].strip() if b" " in status.strip() else b"502")]
    while True:
        line = reply.readline()
        if line in (b"\r\n", b"\n", b""):
            break
        if line.split(b":", 1)[0].strip().lower() not in DROP_HEADERS:
            head.append(line.rstrip(b"\r\n"))
    out = sys.stdout.buffer
    out.write(b"\r\n".join(head) + b"\r\n\r\n")
    try:
        while True:
            chunk = reply.read1(65536)
            if not chunk:
                break
            out.write(chunk)
        out.flush()
    except OSError:
        pass  # the response had already started: end it here rather than send a second one
    return True


def unavailable():
    sys.stdout.write("Status: 503 Service Unavailable\r\nContent-Type: text/plain\r\nRetry-After: 5\r\n\r\n"
                     "The site is restarting. Please go back and try again in a moment.\n")


def main():
    if not FORWARD or os.environ.get("NEXOPAY_BRIDGE_DIRECT"):
        return run_directly()
    # Loading Django here takes a second of CPU: as the PHP forwarder's fallback, only for that forwarder.
    may_run_directly = not PHP_FALLBACK or called_by_php_forwarder()
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(3)
    try:
        conn.connect(APP_SOCKET)
    except OSError:
        conn.close()
        # App server down: serve the slow way rather than fail.
        return run_directly() if may_run_directly else unavailable()
    conn.settimeout(120)
    try:
        if forward(conn):
            return
    except OSError:
        pass
    finally:
        conn.close()
    if may_run_directly and os.environ.get("REQUEST_METHOD", "GET") in ("GET", "HEAD"):
        return run_directly()  # nothing was sent yet and it's safe to repeat
    unavailable()


main()
PY
  } > "$CGI_SCRIPT.new"
  chmod 755 "$(dirname "$CGI_SCRIPT")" "$CGI_SCRIPT.new"
  mv -f "$CGI_SCRIPT.new" "$CGI_SCRIPT"  # atomic: requests in progress never see a half-written script
}

main "$@"
exit
