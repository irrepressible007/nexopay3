"""
Base settings shared by every environment.

All environment-specific values come from environment variables (or a local
`.env` file) so the same code runs on cPanel today and on a VPS later.
"""
from pathlib import Path

import environ
from django.templatetags.static import static
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(env_file)

SECRET_KEY = env("SECRET_KEY", default="dev-insecure-key-change-me")
FIELD_ENCRYPTION_KEY = env("FIELD_ENCRYPTION_KEY", default="")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
SITE_URL = env("SITE_URL", default="http://localhost:8000").rstrip("/")
# Staging only: offer the fake "Test payment" gateway. Never enable on the live site.
ALLOW_MOCK_PAYMENTS = env.bool("ALLOW_MOCK_PAYMENTS", default=False)

INSTALLED_APPS = [
    # modeltranslation must precede django.contrib.admin
    "modeltranslation",
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django.contrib.sitemaps",
    "allauth",
    "allauth.account",
    "storages",
    "django_tasks",
    "django_tasks_db",
    # Nexopay apps
    "apps.core",
    "apps.accounts",
    "apps.organizers",
    "apps.events",
    "apps.orders",
    "apps.tickets",
    "apps.payments",
    "apps.cms",
    "apps.support",
]

MIDDLEWARE = [
    "apps.core.cloudflare.CloudflareRealIPMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "apps.cms.middleware.SiteTextMiddleware",
    "apps.core.middleware.MaintenanceModeMiddleware",
]

ROOT_URLCONF = "nexopay.urls"
WSGI_APPLICATION = "nexopay.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
                "apps.cms.context_processors.site",
            ],
        },
    },
]

# --- Database -------------------------------------------------------------
# cPanel provides MySQL/MariaDB. SQLite is only a local-dev convenience.
DATABASES = {
    "default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
}
if DATABASES["default"]["ENGINE"] == "django.db.backends.mysql":
    DATABASES["default"].setdefault("OPTIONS", {}).update(
        {
            "charset": "utf8mb4",
            "isolation_level": "read committed",
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
        }
    )
    DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
    DATABASES["default"]["TEST"] = {"CHARSET": "utf8mb4", "COLLATION": "utf8mb4_unicode_ci"}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
# allauth's conditional unique index is unsupported on MariaDB; email uniqueness is enforced on User.email.
SILENCED_SYSTEM_CHECKS = ["models.W036"]
FORMS_URLFIELD_ASSUME_HTTPS = True
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

# --- Accounts (django-allauth) ------------------------------------------------
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = env("ACCOUNT_EMAIL_VERIFICATION", default="mandatory")
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True
ACCOUNT_SESSION_REMEMBER = True
ACCOUNT_RATE_LIMITS = {"login_failed": "10/m/ip,5/5m/key"}
ACCOUNT_FORMS = {"signup": "apps.accounts.forms.SignupForm"}
ACCOUNT_ADAPTER = "apps.accounts.adapter.AccountAdapter"
LOGIN_REDIRECT_URL = "accounts:tickets"
LOGIN_URL = "account_login"

# --- Internationalisation ------------------------------------------------------
LANGUAGE_CODE = "en"
LANGUAGES = [("en", _("English")), ("bn", _("Bangla"))]
LOCALE_PATHS = [BASE_DIR / "locale"]
MODELTRANSLATION_DEFAULT_LANGUAGE = "en"
MODELTRANSLATION_FALLBACK_LANGUAGES = ("en",)
TIME_ZONE = "Asia/Dhaka"
USE_I18N = True
USE_TZ = True

# --- Static & media -----------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = env("STATIC_ROOT", default=str(BASE_DIR / "staticfiles"))
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = env("MEDIA_URL", default="/media/")
MEDIA_ROOT = env("MEDIA_ROOT", default=str(BASE_DIR / "media"))
# Uploads may be served straight by the web server, which runs as another user.
FILE_UPLOAD_PERMISSIONS = 0o644
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o755

# Cloudflare R2 (S3-compatible). When R2_BUCKET is unset (local dev) media
# falls back to local disk; production must set it — never store uploads on
# the app server.
R2_BUCKET = env("R2_BUCKET", default="")
R2_PRIVATE_BUCKET = env("R2_PRIVATE_BUCKET", default=R2_BUCKET)
if R2_BUCKET:
    _r2_common = {
        "access_key": env("R2_ACCESS_KEY_ID"),
        "secret_key": env("R2_SECRET_ACCESS_KEY"),
        "endpoint_url": env("R2_ENDPOINT_URL"),
        "region_name": "auto",
        "signature_version": "s3v4",
        "file_overwrite": False,
    }
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                **_r2_common,
                "bucket_name": R2_BUCKET,
                "custom_domain": env("R2_PUBLIC_DOMAIN", default=None),
                "querystring_auth": False,
                "object_parameters": {"CacheControl": "public, max-age=31536000, immutable"},
            },
        },
        "private": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                **_r2_common,
                "bucket_name": R2_PRIVATE_BUCKET,
                "location": "private",
                "querystring_auth": True,
                "querystring_expire": 600,
            },
        },
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
else:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": str(BASE_DIR / "private_media"), "base_url": "/private-media/"},
        },
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }

# --- Cache ----------------------------------------------------------------------
# No Redis on shared hosting: a file cache is fast enough for fragments.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": env("CACHE_DIR", default=str(BASE_DIR / ".cache")),
        "TIMEOUT": 300,
        "OPTIONS": {"MAX_ENTRIES": 5000},
    }
}
RATELIMIT_USE_CACHE = "default"
SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"

# --- Background tasks -----------------------------------------------------------
# Tasks are stored in the DB and processed by `manage.py db_worker --batch`
# from cron (see deploy/crontab.txt).
TASKS = {"default": {"BACKEND": env("TASKS_BACKEND", default="django_tasks_db.DatabaseBackend")}}

# --- Email ----------------------------------------------------------------------
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=465)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=True)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
EMAIL_TIMEOUT = 20
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Nexopay <tickets@nexopay.com.bd>")
SERVER_EMAIL = DEFAULT_FROM_EMAIL
ANYMAIL = env.dict("ANYMAIL", default={})

# --- Nexopay business settings --------------------------------------------------
NEXOPAY = {
    "HOLD_MINUTES": env.int("HOLD_MINUTES", default=15),
    "CURRENCY": "BDT",
    "TICKET_SIGNING_SALT": "nexopay.ticket.v1",
    "PAYMENT_HTTP_TIMEOUT": env.int("PAYMENT_HTTP_TIMEOUT", default=15),
}

# --- Admin (django-unfold) ------------------------------------------------------
ADMIN_URL = env("ADMIN_URL", default="control-room/")

UNFOLD = {
    "SITE_TITLE": "Nexopay Admin",
    "SITE_HEADER": "Nexopay",
    "SITE_ICON": lambda request: static("img/icon-192.png"),
    "SITE_LOGO": lambda request: static("img/logo-on-dark.png"),
    "SITE_FAVICONS": [{"rel": "icon", "sizes": "48x48", "type": "image/png", "href": lambda request: static("img/favicon-48.png")}],
    "THEME": "dark",
    "COLORS": {
        # The site's violet (#7351F5 at 500), so the admin matches the public pages.
        "primary": {
            "50": "243 240 255", "100": "233 227 254", "200": "213 202 253",
            "300": "184 166 251", "400": "150 124 248", "500": "115 81 245",
            "600": "97 60 229", "700": "82 46 196", "800": "67 38 160",
            "900": "55 33 128", "950": "34 20 82",
        },
    },
    "SIDEBAR": {"show_search": True, "show_all_applications": True},
    "DASHBOARD_CALLBACK": "apps.core.admin_dashboard.dashboard_callback",
    "ENVIRONMENT": "apps.core.admin_dashboard.environment_callback",
}

# --- Logging --------------------------------------------------------------------
LOG_DIR = Path(env("LOG_DIR", default=str(BASE_DIR / "logs")))
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"std": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "std"},
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "nexopay.log"),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "std",
            "encoding": "utf-8",
        },
    },
    "root": {"handlers": ["console", "file"], "level": "INFO"},
    "loggers": {
        "apps.payments": {"level": "INFO"},
        "django.db.backends": {"level": "WARNING"},
        "fontTools": {"level": "WARNING"},
    },
}
