"""Entry point for cPanel's "Setup Python App" (Passenger / LiteSpeed)."""
import os
import sys
import traceback
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nexopay.settings.production")

try:
    from nexopay.wsgi import application  # noqa: E402,F401
except Exception:
    # cPanel doesn't always expose the web server's app log: keep the reason for a failed start here.
    (BASE_DIR / "logs").mkdir(exist_ok=True)
    with open(BASE_DIR / "logs" / "startup-error.log", "a", encoding="utf-8") as log:
        log.write(traceback.format_exc() + "\n")
    raise
