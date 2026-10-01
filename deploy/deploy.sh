#!/usr/bin/env bash
# Deploy/update Nexopay on the cPanel server. Run over SSH (cPanel › Terminal):
#     bash ~/nexopay3/deploy/deploy.sh
#     (APP_DIR=/path/to/other/install to deploy a different copy)
#
# Everything lives inside main() so bash reads the whole file before running it:
# the script updates itself with `git pull`, which would otherwise corrupt a run.
set -euo pipefail

main() {
  APP_DIR="${APP_DIR:-$HOME/nexopay3}"
  APP_NAME="$(basename "$APP_DIR")"
  VENV="${VENV:-$(ls -d "$HOME"/virtualenv/"$APP_NAME"/3.* 2>/dev/null | sort -V | tail -1)}"
  export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-nexopay.settings.production}"

  if [ -z "$VENV" ] || [ ! -f "$VENV/bin/activate" ]; then
    echo "Virtualenv not found. Create the app in cPanel › Setup Python App first." >&2
    exit 1
  fi
  [ -f "$APP_DIR/.env" ] || { echo "Missing $APP_DIR/.env (run deploy/make_env.sh first)." >&2; exit 1; }

  cd "$APP_DIR"
  mkdir -p tmp logs
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"

  echo "→ Pulling code"
  git pull --ff-only

  echo "→ Installing dependencies"
  # cPanel's sandboxed pkg-config is broken; hand the MySQL build flags over directly.
  if command -v mysql_config >/dev/null 2>&1; then
    MYSQLCLIENT_CFLAGS="$(mysql_config --cflags 2>/dev/null || true)"
    MYSQLCLIENT_LDFLAGS="$(mysql_config --libs 2>/dev/null || true)"
    export MYSQLCLIENT_CFLAGS MYSQLCLIENT_LDFLAGS
  fi
  pip install --quiet --upgrade pip
  if ! pip install --quiet -r requirements.txt 2>tmp/pip.log; then
    if grep -q mysqlclient tmp/pip.log; then
      echo "  (fast MySQL driver can't be compiled here — using the PyMySQL driver instead)"
      grep -v '^mysqlclient' requirements.txt > tmp/requirements-no-mysqlclient.txt
      pip install --quiet -r tmp/requirements-no-mysqlclient.txt PyMySQL
    else
      cat tmp/pip.log >&2
      exit 1
    fi
  fi

  echo "→ Checking database character set (Bangla needs utf8mb4)"
  python manage.py ensure_utf8mb4

  echo "→ Migrating database"
  python manage.py migrate --noinput

  echo "→ Collecting static files"
  python manage.py collectstatic --noinput --verbosity 0
  web_readable
  guard_uploads

  echo "→ Checking configuration"
  python manage.py check --deploy --fail-level ERROR

  echo "→ Restarting app"
  touch tmp/restart.txt
  bash deploy/appserver.sh reload  # the bridge's fast mode keeps Python running: load the new code
  echo "✓ Deployed $(git rev-parse --short HEAD)"
}

# The web server serves static and uploaded files itself, so it must be able to read them.
web_readable() {
  local var dir
  for var in STATIC_ROOT MEDIA_ROOT; do
    dir="$(grep -E "^$var=" .env | cut -d= -f2- || true)"
    if [ -n "$dir" ] && [ -d "$dir" ]; then chmod -R go+rX "$dir"; fi
  done
}

# When uploads live under public_html, Apache serves them itself. Make sure an uploaded file can
# never run as a script (.php etc.), folders aren't listed, and SVG/HTML can't run JavaScript.
guard_uploads() {
  local dir
  dir="$(grep -E "^MEDIA_ROOT=" .env | cut -d= -f2- || true)"
  [ -n "$dir" ] && [ -d "$dir" ] || return 0
  cat > "$dir/.htaccess" <<'HTACCESS'
# Written by deploy/deploy.sh: uploaded files are data, never code. Edits here are overwritten.
Options -Indexes
<FilesMatch "\.(?i:php[0-9]?|phtml|phar|pht|phps|pl|py|pyc|cgi|fcgi|sh|bash|asp|aspx|jsp|shtml|htaccess|htpasswd|ini|env|log|sql)$">
  Require all denied
</FilesMatch>
<IfModule mod_headers.c>
  Header set X-Content-Type-Options "nosniff"
  <FilesMatch "\.(?i:svg|xml|html?)$">
    Header set Content-Security-Policy "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox"
  </FilesMatch>
</IfModule>
HTACCESS
  chmod 644 "$dir/.htaccess"
}

main "$@"
exit
