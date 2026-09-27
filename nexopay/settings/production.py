from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False

# Cloudflare terminates TLS and forwards to cPanel over HTTPS (Full strict).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 30)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"

EMAIL_BACKEND = env("EMAIL_BACKEND", default="apps.core.mail.SiteEmailBackend")

ADMINS = [("Nexopay Ops", env("ADMIN_EMAIL", default="admin@nexopay.com.bd"))]
