from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
ACCOUNT_EMAIL_VERIFICATION = "optional"
TASKS = {"default": {"BACKEND": "django_tasks.backends.immediate.ImmediateBackend"}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}  # noqa: F405
RATELIMIT_ENABLE = False
# Tests default to SQLite; set TEST_DATABASE_URL to a MySQL URL to run the
# locking/concurrency tests against the production engine.
if env("TEST_DATABASE_URL", default=""):
    DATABASES = {"default": env.db("TEST_DATABASE_URL")}  # noqa: F405
    DATABASES["default"]["ENGINE"] = "nexopay.dbbackend"
    DATABASES["default"]["OPTIONS"] = {
        "charset": "utf8mb4",
        "isolation_level": "read committed",
        "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
    }
    DATABASES["default"]["TEST"] = {"CHARSET": "utf8mb4", "COLLATION": "utf8mb4_unicode_ci"}
