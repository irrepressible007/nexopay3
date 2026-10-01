#!/usr/bin/env bash
# Move Nexopay 3 from its staging address onto the main domain, replacing the old
# Nexopay 2 (Laravel) site in ~/public_html. Run over SSH (cPanel › Terminal):
#
#   bash ~/nexopay3/deploy/cutover.sh check      # read-only: what would happen, and any blockers
#   bash ~/nexopay3/deploy/cutover.sh go         # do it; asks before each step that can't be undone
#   bash ~/nexopay3/deploy/cutover.sh finish     # if go stopped at its very last check: check again, record it
#   bash ~/nexopay3/deploy/cutover.sh rollback   # put Nexopay 2 back exactly as it was
#   bash ~/nexopay3/deploy/cutover.sh status
#
# `go`, step by step:
#   1. backs up the Nexopay 3 database
#   2. moves everything in ~/public_html (the old site) into ~/nexopay2-public_html-<time> and shows
#      a "back in a few minutes" page meanwhile. Kept in place: .well-known (SSL renewals), cgi-bin,
#      PHP settings files, and folders of other domains. ~/nexopay2 and its database are NOT touched.
#   3. pauses the old site's cron jobs (rollback resumes them)
#   4. points .env at the main domain and switches the test payment gateway off
#   5. deploys (code, database, static files) and clears demo/test data - you see the list first
#   6. connects ~/public_html to the app server (deploy/cgi_bridge.sh fast) and checks the live site
#
# Everything lives inside main() so bash reads the whole file first (deploy.sh pulls new code).
set -Eeuo pipefail

main() {
  APP_DIR="${APP_DIR:-$HOME/nexopay3}"
  APP_NAME="$(basename "$APP_DIR")"
  VENV="${VENV:-$(ls -d "$HOME"/virtualenv/"$APP_NAME"/3.* 2>/dev/null | sort -V | tail -1)}"
  PY="$VENV/bin/python"
  ENV_FILE="$APP_DIR/.env"
  DOMAIN="${DOMAIN:-nexopay.com.bd}"
  LIVE_ROOT="${LIVE_ROOT:-$HOME/public_html}"
  STATE_DIR="$APP_DIR/tmp/cutover"
  STATE="$STATE_DIR/state"
  PAUSE_TAG="#nexopay2-paused# "
  KEEP=(.well-known cgi-bin .user.ini php.ini)
  export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-nexopay.settings.production}"

  [ -x "$PY" ] || { echo "Virtualenv not found ($VENV)." >&2; exit 1; }
  [ -f "$ENV_FILE" ] || { echo "Missing $ENV_FILE." >&2; exit 1; }
  mkdir -p "$STATE_DIR"
  chmod 700 "$STATE_DIR"
  cd "$APP_DIR"

  case "${1:-status}" in
    check) check ;;
    go) go ;;
    finish) finish ;;
    rollback) rollback ;;
    status) status ;;
    *) echo "Usage: $0 check|go|finish|rollback|status" >&2; exit 1 ;;
  esac
}

# --- small helpers ----------------------------------------------------------------------------
env_get() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- || true; }

env_set() {  # env_set KEY VALUE - replaces the line or appends it; the file keeps its mode
  "$PY" - "$ENV_FILE" "$1" "$2" <<'PY'
import sys
path, key, value = sys.argv[1:4]
lines = open(path, encoding="utf-8").read().splitlines()
out, done = [], False
for line in lines:
    if line.startswith(key + "="):
        if not done:
            out.append(f"{key}={value}")
            done = True
        continue
    out.append(line)
if not done:
    out.append(f"{key}={value}")
open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
PY
}

state_get() { grep -E "^$1=" "$STATE" 2>/dev/null | cut -d= -f2- || true; }
say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
manage() { "$PY" manage.py "$@"; }

# Folders of other domains/subdomains that live inside public_html: they must stay where they are.
nested_docroots() {
  command -v uapi >/dev/null 2>&1 || return 0
  uapi --output=json DomainInfo domains_data 2>/dev/null | "$PY" -c '
import json, os, sys
root = os.path.realpath(sys.argv[1])
try:
    data = json.load(sys.stdin)["result"]["data"]
except Exception:
    sys.exit(0)
domains = data.get("addon_domains", []) + data.get("sub_domains", []) + data.get("parked_domains", [])
for d in domains:
    doc = os.path.realpath(d.get("documentroot") or "")
    if doc.startswith(root + os.sep):
        print(os.path.relpath(doc, root).split(os.sep)[0])
' "$LIVE_ROOT" | sort -u
}

main_docroot() {
  command -v uapi >/dev/null 2>&1 || return 0
  uapi --output=json DomainInfo domains_data 2>/dev/null | "$PY" -c '
import json, sys
try:
    print(json.load(sys.stdin)["result"]["data"]["main_domain"]["documentroot"])
except Exception:
    pass'
}

is_kept() {
  local name="$1" k
  for k in "${KEEP[@]}"; do [ "$name" = "$k" ] && return 0; done
  return 1
}

cpanel_blocks() {  # the cPanel-generated parts of an .htaccess (PHP version handler, php.ini directives)
  [ -f "$1" ] || return 0
  awk '/^# .*BEGIN cPanel-generated/{on=1} on{print} /^# .*END cPanel-generated/{on=0}' "$1"
}

origin_curl() {  # curl the live domain on this server directly (skipping Cloudflare) when possible
  local ip
  for ip in $(hostname -I 2>/dev/null || true) 127.0.0.1; do
    # Only an address that serves *this* site's stylesheet counts: 127.0.0.1 may be the server's default site.
    if [ "$(curl -sk -m 10 -o /dev/null -w '%{http_code}' --resolve "$DOMAIN:443:$ip" \
          "https://$DOMAIN/static/css/app.css" 2>/dev/null)" = 200 ]; then
      curl -sk -m 60 --resolve "$DOMAIN:443:$ip" "$@"
      return
    fi
  done
  curl -s -m 60 "$@"
}

# --- check (read-only) --------------------------------------------------------------------------
check() {
  BLOCKERS=()
  local site static_root media_root mock docroot entries nested
  site="$(env_get SITE_URL)"; static_root="$(env_get STATIC_ROOT)"; media_root="$(env_get MEDIA_ROOT)"
  mock="$(env_get ALLOW_MOCK_PAYMENTS)"

  say "Nexopay 3 now"
  echo "  app folder:      $APP_DIR ($(git rev-parse --short HEAD 2>/dev/null || echo '?'))"
  echo "  address:         ${site:-?}"
  echo "  static / media:  ${static_root:-?} / ${media_root:-?}"
  echo "  test gateway:    ${mock:-False}  → will be switched off"
  echo "  control room:    /$(env_get ADMIN_URL)"
  if [ "$site" = "https://$DOMAIN" ]; then
    echo "  ✓ Already running on https://$DOMAIN (nothing to move)."
    return 0
  fi

  say "Main domain $DOMAIN"
  docroot="$(main_docroot)"
  echo "  document root:   ${docroot:-unknown (uapi not available)}"
  if [ -n "$docroot" ] && [ "$(realpath "$docroot")" != "$(realpath "$LIVE_ROOT")" ]; then
    BLOCKERS+=("The main domain's document root is $docroot, not $LIVE_ROOT.")
  fi
  if [ -L "$LIVE_ROOT" ]; then
    BLOCKERS+=("$LIVE_ROOT is a link to $(readlink "$LIVE_ROOT"); this script expects a real folder.")
  elif [ ! -d "$LIVE_ROOT" ]; then
    BLOCKERS+=("$LIVE_ROOT does not exist.")
  else
    echo "  folder:          $(stat -c '%a %U:%G' "$LIVE_ROOT")"
  fi
  nested="$(nested_docroots)"
  if [ -n "$nested" ]; then
    echo "  other domains inside it (stay in place): $(echo "$nested" | tr '\n' ' ')"
  fi
  if grep -qE '^\s*PassengerAppRoot' "$LIVE_ROOT/.htaccess" 2>/dev/null; then
    BLOCKERS+=("A cPanel Python app is attached to $DOMAIN. Stop it first (Setup Python App › Stop app).")
  fi

  say "Old site files that will move to ~/nexopay2-public_html-<time>"
  shopt -s dotglob nullglob
  entries=()
  local path name
  for path in "$LIVE_ROOT"/*; do
    name="$(basename "$path")"
    is_kept "$name" || grep -qxF "$name" <<<"$nested" || entries+=("$name")
  done
  shopt -u dotglob nullglob
  echo "  ${#entries[@]} items: $(printf '%s ' "${entries[@]:0:25}")$([ ${#entries[@]} -gt 25 ] && echo '…')"
  echo "  staying:         $(printf '%s ' "${KEEP[@]}")"
  echo "  cPanel settings carried over from its .htaccess:"
  cpanel_blocks "$LIVE_ROOT/.htaccess" | grep -E '^# .*BEGIN' | sed 's/^/    /' || true

  say "Old site's scheduled jobs (paused by go, resumed by rollback)"
  crontab -l 2>/dev/null | grep -F nexopay2 | grep -vF "$PAUSE_TAG" | sed 's/^/  /' || echo "  none"

  say "Payments on the live site"
  manage shell -c "
from apps.payments.models import PaymentProviderSetting as P, Provider
from apps.payments.providers.base import BasePaymentProvider
from apps.payments.registry import provider_class
live = []
for s in P.objects.filter(is_enabled=True).exclude(provider__in=[Provider.MOCK, Provider.FREE]):
    specs = getattr(provider_class(s.provider), 'CREDENTIALS', [])
    missing = [c.label for c in specs if c.required and not BasePaymentProvider.resolve_credential(s, c.name)]
    live.append(s.provider)
    print('  ', s.provider, 'sandbox' if s.is_sandbox else 'LIVE', '- missing: ' + ', '.join(missing) if missing else '- credentials complete')
if not live:
    print('   No real payment method is switched on: only free tickets can be checked out until one is.')
" 2>/dev/null | grep -v "objects imported" || echo "  (couldn't read the payment settings)"

  say "Demo/test data that go would offer to clear (nothing is changed now)"
  manage purge_test_data 2>/dev/null | sed 's/^/  /'

  say "Disk space"
  df -h "$HOME" 2>/dev/null | tail -1 | awk '{print "  free: "$4" of "$2}'

  if [ ${#BLOCKERS[@]} -gt 0 ]; then
    say "Blockers - fix these first:"
    printf '  ✗ %s\n' "${BLOCKERS[@]}"
    return 1
  fi
  say "No blockers. When ready:  bash $APP_DIR/deploy/cutover.sh go"
}

# --- go ---------------------------------------------------------------------------------------
go() {
  if [ -f "$STATE" ] && [ "$(state_get DONE)" = yes ]; then
    echo "Already moved on $(state_get TS). To undo: bash $APP_DIR/deploy/cutover.sh rollback"
    exit 0
  fi
  if [ "$(env_get SITE_URL)" = "https://$DOMAIN" ]; then
    echo "Nexopay 3 is already set up on https://$DOMAIN - go won't run again."
    echo "  If the move stopped at its last check:  bash $APP_DIR/deploy/cutover.sh finish"
    echo "  To undo it:                             bash $APP_DIR/deploy/cutover.sh rollback"
    exit 1
  fi
  check || exit 1

  local answer admin_path old_site old_host old_media ts backup nested
  echo
  read -rp "Type MOVE to replace the site at https://$DOMAIN with Nexopay 3: " answer
  [ "$answer" = MOVE ] || { echo "Nothing changed."; exit 0; }

  admin_path="$(env_get ADMIN_URL)"; admin_path="${admin_path%/}"
  read -rp "Control room address: /${admin_path}/  - type a new one only you know, or Enter to keep it: " answer
  if [ -n "$answer" ]; then
    answer="${answer#/}"; answer="${answer%/}"
    if [[ "$answer" =~ ^[A-Za-z0-9][A-Za-z0-9-]{3,40}$ ]]; then admin_path="$answer"
    else echo "  (letters, numbers and dashes only, 4-41 long - keeping /${admin_path}/)"; fi
  fi
  local keep_users keep_events
  read -rp "Accounts to keep besides staff (emails separated by spaces, Enter for none): " keep_users
  read -rp "Events to keep (their web address names, e.g. my-concert-2026, Enter for none): " keep_events

  ts="$(date +%Y%m%d-%H%M%S)"
  backup="$(mktemp -d "$HOME/nexopay2-public_html-$ts-XXXX")"  # never collides with an earlier one
  old_site="$(env_get SITE_URL)"; old_host="${old_site#*://}"; old_host="${old_host%%/*}"
  old_media="$(env_get MEDIA_ROOT)"
  nested="$(nested_docroots)"
  printf 'TS=%s\nBACKUP=%s\nENV_BACKUP=%s\nLIVE_ROOT=%s\nDONE=no\n' \
    "$ts" "$backup" "$ENV_FILE.before-cutover-$ts" "$LIVE_ROOT" > "$STATE"

  say "1/6 Backing up the Nexopay 3 database"
  manage backup_db --keep 14

  say "2/6 Moving the old site out of $LIVE_ROOT"
  cp -p "$ENV_FILE" "$ENV_FILE.before-cutover-$ts"
  cpanel_blocks "$LIVE_ROOT/.htaccess" > "$STATE_DIR/cpanel-blocks.htaccess"
  crontab -l > "$STATE_DIR/crontab.before" 2>/dev/null || true
  trap 'on_error' ERR
  chmod 750 "$backup"
  shopt -s dotglob nullglob
  local path name
  : > "$STATE_DIR/moved.txt"
  for path in "$LIVE_ROOT"/*; do
    name="$(basename "$path")"
    if is_kept "$name" || grep -qxF "$name" <<<"$nested"; then continue; fi
    mv "$path" "$backup/"
    echo "$name" >> "$STATE_DIR/moved.txt"
  done
  shopt -u dotglob nullglob
  write_maintenance
  echo "  ✓ $(wc -l < "$STATE_DIR/moved.txt") items moved to $backup - the domain shows a 'back in a few minutes' page"

  say "3/6 Pausing the old site's scheduled jobs"
  if crontab -l 2>/dev/null | grep -F nexopay2 | grep -qvF "$PAUSE_TAG"; then
    crontab -l | awk -v tag="$PAUSE_TAG" 'index($0, "nexopay2") && index($0, tag) != 1 && $0 !~ /^[[:space:]]*#/ {print tag $0; next} {print}' | crontab -
    echo "  ✓ paused"
  else
    echo "  none to pause"
  fi

  say "4/6 Pointing Nexopay 3 at https://$DOMAIN"
  env_set SITE_URL "https://$DOMAIN"
  env_set ALLOWED_HOSTS "$DOMAIN,www.$DOMAIN${old_host:+,$old_host}"
  env_set CSRF_TRUSTED_ORIGINS "https://$DOMAIN,https://www.$DOMAIN${old_host:+,https://$old_host}"
  env_set STATIC_ROOT "$LIVE_ROOT/static"
  env_set MEDIA_ROOT "$LIVE_ROOT/media"
  env_set MEDIA_URL "/media/"
  env_set ALLOW_MOCK_PAYMENTS "False"
  env_set ADMIN_URL "$admin_path/"
  mkdir -p "$LIVE_ROOT/static" "$LIVE_ROOT/media"
  if [ -n "$old_media" ] && [ -d "$old_media" ] && [ "$(realpath "$old_media")" != "$(realpath "$LIVE_ROOT/media")" ]; then
    cp -a "$old_media/." "$LIVE_ROOT/media/"
    echo "  ✓ uploaded images copied from $old_media"
  fi

  say "5/6 Deploying and clearing test data"
  bash "$APP_DIR/deploy/deploy.sh"
  local purge_args=()
  for answer in $keep_users; do purge_args+=(--keep-user "$answer"); done
  for answer in $keep_events; do purge_args+=(--keep-event "$answer"); done
  manage purge_test_data ${purge_args[@]+"${purge_args[@]}"}
  read -rp "Delete the demo/test data listed above? Type DELETE, or Enter to keep it all: " answer
  if [ "$answer" = DELETE ]; then
    manage purge_test_data --yes ${purge_args[@]+"${purge_args[@]}"}
  else
    echo "  kept - you can run it later: cd $APP_DIR && $PY manage.py purge_test_data"
  fi

  say "6/6 Connecting $DOMAIN to the app"
  cat "$STATE_DIR/cpanel-blocks.htaccess" > "$LIVE_ROOT/.htaccess"
  chmod 644 "$LIVE_ROOT/.htaccess"
  bash "$APP_DIR/deploy/cgi_bridge.sh" fast
  rm -f "$LIVE_ROOT/nexopay-maintenance.html"
  smoke_test
  trap - ERR
  sed -i 's/^DONE=.*/DONE=yes/' "$STATE"

  next_steps
}

# The move ran, but its last check stopped it (e.g. it tested the wrong local address): check again.
finish() {
  [ -f "$STATE" ] || { echo "No move recorded - run check, then go."; exit 1; }
  if [ "$(state_get DONE)" = yes ]; then next_steps; return; fi
  [ "$(env_get SITE_URL)" = "https://$DOMAIN" ] || { echo "The move didn't get as far as switching the address - run rollback, then go again."; exit 1; }
  say "Checking https://$DOMAIN"
  rm -f "$LIVE_ROOT/nexopay-maintenance.html"
  smoke_test
  sed -i 's/^DONE=.*/DONE=yes/' "$STATE"
  next_steps
}

next_steps() {
  local old_host admin_path
  old_host="$(grep -E '^SITE_URL=' "$(state_get ENV_BACKUP)" 2>/dev/null | cut -d= -f2- | sed 's#^https\?://##; s#/.*##' || true)"
  admin_path="$(env_get ADMIN_URL)"
  say "✓ Nexopay 3 is live at https://$DOMAIN"
  cat <<NEXT
  Old site files:   $(state_get BACKUP)   (its code ~/nexopay2 and database are untouched)
  Control room:     https://$DOMAIN/${admin_path%/}/
  Undo everything:  bash $APP_DIR/deploy/cutover.sh rollback

  Now, in the Cloudflare dashboard for $DOMAIN:
    • Caching › Configuration › Purge Everything   (drops the old site's cached files)
    • SSL/TLS › Edge Certificates: "Always Use HTTPS" on, "Minimum TLS Version" 1.2
    • Any cache rule written for ${old_host:-the staging address}: make it cover $DOMAIN too
  And with each payment provider (bKash, Nagad, Upay, SSLCommerz merchant panels):
    • the registered website / callback domain must be https://$DOMAIN
NEXT
}

on_error() {
  local code=$?
  trap - ERR
  echo
  echo "✗ A step failed (exit $code). The old site's files are safe in $(state_get BACKUP)."
  echo "  To put Nexopay 2 back right away:  bash $APP_DIR/deploy/cutover.sh rollback"
  exit "$code"
}

write_maintenance() {
  cat > "$LIVE_ROOT/nexopay-maintenance.html" <<'HTML'
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>Nexopay | Back in a few minutes</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;padding:1.5rem;box-sizing:border-box;background:#0c0c0f;color:#f2f2f4;font-family:system-ui,"Segoe UI","Hind Siliguri",sans-serif;text-align:center}main{max-width:30rem}h1{font-size:clamp(1.6rem,5vw,2.2rem);margin:0 0 .6rem}p{color:#a2a2a8;line-height:1.6;margin:.4rem 0}b{color:#a593ff}</style></head>
<body><main><p><b>nexopay</b></p><h1>We're moving to our new site</h1><p>Back in a few minutes. Thank you for waiting.</p>
<p lang="bn">আমরা নতুন সাইটে যাচ্ছি। কয়েক মিনিটের মধ্যে ফিরে আসছি।</p></main></body></html>
HTML
  chmod 644 "$LIVE_ROOT/nexopay-maintenance.html"
  {
    cat "$STATE_DIR/cpanel-blocks.htaccess"
    cat <<'HT'
# BEGIN NEXOPAY MAINTENANCE
ErrorDocument 503 /nexopay-maintenance.html
<IfModule mod_rewrite.c>
RewriteEngine On
RewriteCond %{REQUEST_URI} !^/nexopay-maintenance\.html$
RewriteCond %{REQUEST_URI} !^/\.well-known/
RewriteRule ^ - [R=503,L]
</IfModule>
<IfModule mod_headers.c>
Header always set Cache-Control "no-store"
Header always set Retry-After "300"
</IfModule>
# END NEXOPAY MAINTENANCE
HT
  } > "$LIVE_ROOT/.htaccess"
  chmod 644 "$LIVE_ROOT/.htaccess"
}

smoke_test() {
  local code body css
  body="$(origin_curl -s "https://$DOMAIN/" -w '\n%{http_code}')"
  code="${body##*$'\n'}"
  if [ "$code" != 200 ] || ! grep -q '/static/css/app\.' <<<"$body"; then
    echo "✗ The home page gave HTTP $code instead of the Nexopay 3 page." >&2
    return 1
  fi
  echo "  ✓ home page"
  code="$(origin_curl -s -o /dev/null -w '%{http_code}' "https://$DOMAIN/accounts/login/")"
  [ "$code" = 200 ] || { echo "✗ The login page gave HTTP $code." >&2; return 1; }
  echo "  ✓ login page"
  css="$(cd "$LIVE_ROOT" && ls static/css/app.*.css 2>/dev/null | head -1 || true)"
  if [ -n "$css" ]; then
    code="$(origin_curl -s -o /dev/null -w '%{http_code}' "https://$DOMAIN/$css")"
    [ "$code" = 200 ] || { echo "✗ The stylesheet gave HTTP $code." >&2; return 1; }
    echo "  ✓ stylesheet"
  fi
  code="$(origin_curl -s -o /dev/null -w '%{http_code}' "https://$DOMAIN/login")"
  [ "$code" = 301 ] && echo "  ✓ old Nexopay 2 links redirect" || echo "  ! /login gave HTTP $code (expected a redirect)"
}

# --- rollback ---------------------------------------------------------------------------------
rollback() {
  [ -f "$STATE" ] || { echo "No cutover recorded - nothing to roll back."; exit 0; }
  local backup env_backup ts answer parked path name
  backup="$(state_get BACKUP)"; env_backup="$(state_get ENV_BACKUP)"; ts="$(date +%Y%m%d-%H%M%S)"
  [ -d "$backup" ] || { echo "The old site's backup folder $backup is missing." >&2; exit 1; }
  read -rp "Type ROLLBACK to put Nexopay 2 back on https://$DOMAIN: " answer
  [ "$answer" = ROLLBACK ] || { echo "Nothing changed."; exit 0; }

  say "Taking Nexopay 3 off $LIVE_ROOT"
  parked="$(mktemp -d "$HOME/nexopay3-public_html-rolledback-$ts-XXXX")"
  chmod 750 "$parked"
  local nested
  nested="$(nested_docroots)"
  shopt -s dotglob nullglob
  for path in "$LIVE_ROOT"/*; do  # the mirror of go: everything except what go left in place
    name="$(basename "$path")"
    if is_kept "$name" || grep -qxF "$name" <<<"$nested"; then continue; fi
    mv "$path" "$parked/"
  done
  [ -f "$LIVE_ROOT/cgi-bin/nexopay.cgi" ] && mv "$LIVE_ROOT/cgi-bin/nexopay.cgi" "$parked/"

  say "Putting Nexopay 2 back"
  for path in "$backup"/*; do
    mv "$path" "$LIVE_ROOT/"
  done
  shopt -u dotglob nullglob
  rmdir "$backup" 2>/dev/null || true

  say "Restoring Nexopay 3's previous settings (staging address)"
  if [ -f "$env_backup" ]; then
    cp -p "$env_backup" "$ENV_FILE"
    bash "$APP_DIR/deploy/appserver.sh" reload || true
  fi
  if crontab -l 2>/dev/null | grep -qF "$PAUSE_TAG"; then
    crontab -l | sed "s|^$PAUSE_TAG||" | crontab -
    echo "  ✓ old site's scheduled jobs resumed"
  fi
  mv "$STATE" "$STATE_DIR/state.rolledback-$ts"

  say "✓ Nexopay 2 is back on https://$DOMAIN"
  echo "  Nexopay 3's files from the live period: $parked (uploads made meanwhile are in its media folder)."
  echo "  The test-data clean-up is not undone; the database backup from step 1 is in the backups folder."
  echo "  In Cloudflare: Caching › Purge Everything."
}

status() {
  echo "Address:      $(env_get SITE_URL)"
  if [ -f "$STATE" ]; then
    echo "Cutover:      $( [ "$(state_get DONE)" = yes ] && echo done || echo 'started, not finished') ($(state_get TS))"
    echo "Old site in:  $(state_get BACKUP)"
  else
    echo "Cutover:      not done"
  fi
  bash "$APP_DIR/deploy/cgi_bridge.sh" status 2>/dev/null || true
}

main "$@"
exit
