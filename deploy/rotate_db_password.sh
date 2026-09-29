#!/usr/bin/env bash
# Give the site's database user a new password - in cPanel and in .env together.
# If anything fails, the old password is put back everywhere.
#
#   bash ~/nexopay3/deploy/rotate_db_password.sh            # a random one nobody sees or types
#   bash ~/nexopay3/deploy/rotate_db_password.sh --choose   # one you type (hidden, asked twice)
#
# Also pins FIELD_ENCRYPTION_KEY (to the current SECRET_KEY, so nothing already saved
# changes): secrets stored in the admin then stay readable even if SECRET_KEY changes.
set -euo pipefail

main() {
  APP_DIR="${APP_DIR:-$HOME/nexopay3}"
  APP_NAME="$(basename "$APP_DIR")"
  VENV="${VENV:-$(ls -d "$HOME"/virtualenv/"$APP_NAME"/3.* 2>/dev/null | sort -V | tail -1)}"
  PY="$VENV/bin/python"
  ENV_FILE="$APP_DIR/.env"
  [ -f "$ENV_FILE" ] || { echo "No $ENV_FILE - run deploy/make_env.sh first." >&2; exit 1; }
  command -v uapi >/dev/null 2>&1 || { echo "uapi not found - run this in cPanel's Terminal." >&2; exit 1; }

  local db_user old_password new_password
  db_user="$(db_url_part user)"
  old_password="$(db_url_part password)"
  if [ "${1:-}" = "--choose" ]; then
    new_password="$(ask_password)"
  else
    new_password="$("$PY" -c 'import secrets, string; a = string.ascii_letters + string.digits; print("".join(secrets.choice(a) for _ in range(32)))')"
  fi

  printf '%s' "$new_password" | "$PY" -c "$REWRITE_ENV" "$ENV_FILE" "$ENV_FILE.new"
  echo "→ Setting a new password for database user $db_user in cPanel"
  if ! set_password "$db_user" "$new_password"; then
    rm -f "$ENV_FILE.new"
    echo "cPanel didn't accept it - nothing was changed." >&2
    exit 1
  fi
  cp -p "$ENV_FILE" "$ENV_FILE.before-rotate"
  mv -f "$ENV_FILE.new" "$ENV_FILE"

  echo "→ Checking the site can connect with it"
  if (cd "$APP_DIR" && "$PY" manage.py shell -c "from django.db import connection; connection.ensure_connection()") >/dev/null 2>&1; then
    rm -f "$ENV_FILE.before-rotate"
    bash "$APP_DIR/deploy/appserver.sh" reload
    echo "✓ Database password changed. The old one no longer works anywhere."
  else
    echo "The site couldn't connect with the new password - putting the old one back." >&2
    mv -f "$ENV_FILE.before-rotate" "$ENV_FILE"
    if set_password "$db_user" "$old_password"; then
      echo "Old password restored; nothing changed." >&2
    else
      echo "Couldn't restore it either: set a password in cPanel > MySQL Databases, then" >&2
      echo "mv $ENV_FILE $ENV_FILE.old && bash $APP_DIR/deploy/make_env.sh" >&2
    fi
    exit 1
  fi
}

ask_password() {  # prompts go to the screen; only the password is returned
  local first second
  while :; do
    read -rsp "New database password (hidden): " first; echo >&2
    read -rsp "Type it again: " second; echo >&2
    if [ -n "$first" ] && [ "$first" = "$second" ]; then break; fi
    echo "Empty, or the two didn't match - try again." >&2
  done
  printf '%s' "$first"
}

# user or password from DATABASE_URL in .env (password URL-decoded)
db_url_part() {
  "$PY" - "$ENV_FILE" "$1" <<'PY'
import sys
import urllib.parse

path, part = sys.argv[1], sys.argv[2]
for line in open(path, encoding="utf-8"):
    if line.startswith("DATABASE_URL="):
        url = urllib.parse.urlsplit(line.split("=", 1)[1].strip())
        print(urllib.parse.unquote(url.username if part == "user" else url.password or ""))
        break
else:
    sys.exit("DATABASE_URL is missing from .env")
PY
}

set_password() {  # user password -> 0 if cPanel accepted it
  uapi --output=json Mysql set_password user="$1" password="$2" 2>/dev/null | "$PY" -c '
import json, sys
try:
    data = json.load(sys.stdin)
except ValueError:
    sys.exit("  cPanel gave an unreadable answer")
result = data.get("result", data)
if result.get("status") != 1:
    sys.exit("  cPanel: " + "; ".join(result.get("errors") or ["unknown error"]))
'
}

# .env with the new DATABASE_URL password (stdin) and FIELD_ENCRYPTION_KEY pinned; written mode 600
read -r -d '' REWRITE_ENV <<'PY' || true
import os
import re
import sys
import urllib.parse

src, dst = sys.argv[1], sys.argv[2]
password = urllib.parse.quote(sys.stdin.read(), safe="")
lines = open(src, encoding="utf-8").read().splitlines()
values = dict(line.split("=", 1) for line in lines if "=" in line and not line.startswith("#"))
out = []
for line in lines:
    if line.startswith("DATABASE_URL="):
        line = re.sub(r"^(DATABASE_URL=\w+://[^:/@]+:)[^@]*@", lambda m: m.group(1) + password + "@", line)
    elif line.startswith("FIELD_ENCRYPTION_KEY=") and not values.get("FIELD_ENCRYPTION_KEY"):
        continue  # an empty one: replaced below
    out.append(line)
if not values.get("FIELD_ENCRYPTION_KEY") and values.get("SECRET_KEY"):
    out.append("# Key for secrets saved in the admin, pinned so they stay readable if SECRET_KEY changes.")
    out.append("FIELD_ENCRYPTION_KEY=" + values["SECRET_KEY"])
fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as f:
    f.write("\n".join(out) + "\n")
PY

main "$@"
exit
