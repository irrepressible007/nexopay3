#!/usr/bin/env bash
# Deploy/update Nexopay on the cPanel server. Run over SSH (cPanel › Terminal):
#     bash ~/nexopay/deploy/deploy.sh            # production
#     APP_DIR=~/nexopay-staging bash ~/nexopay-staging/deploy/deploy.sh
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/nexopay}"
APP_NAME="$(basename "$APP_DIR")"
VENV="${VENV:-$(ls -d "$HOME"/virtualenv/"$APP_NAME"/3.* 2>/dev/null | sort -V | tail -1)}"
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-nexopay.settings.production}"

if [ -z "$VENV" ] || [ ! -f "$VENV/bin/activate" ]; then
  echo "Virtualenv not found. Create the app in cPanel › Setup Python App first." >&2
  exit 1
fi
[ -f "$APP_DIR/.env" ] || { echo "Missing $APP_DIR/.env (copy .env.example and fill it in)." >&2; exit 1; }

cd "$APP_DIR"
# shellcheck disable=SC1091
source "$VENV/bin/activate"

echo "→ Pulling code"
git pull --ff-only

echo "→ Installing dependencies"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt || {
  echo "mysqlclient failed to build? Installing PyMySQL fallback."
  grep -v '^mysqlclient' requirements.txt > /tmp/nexopay-req.txt
  pip install --quiet -r /tmp/nexopay-req.txt PyMySQL
}

echo "→ Migrating database"
python manage.py migrate --noinput

echo "→ Collecting static files"
python manage.py collectstatic --noinput --verbosity 0

echo "→ Checking configuration"
python manage.py check --deploy --fail-level ERROR

echo "→ Restarting app"
mkdir -p tmp logs
touch tmp/restart.txt
echo "✓ Deployed $(git rev-parse --short HEAD)"
