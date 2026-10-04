import os
from pathlib import Path
from decouple import config, Csv
from urllib.parse import urlparse


# ============================================================
# SECURITY
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config("DJANGO_SECRET_KEY", default="dev-secret-key-change-in-production-collectnaija-2026")
DEBUG = config("DEBUG", default=False, cast=bool)

ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS",
    default="localhost,127.0.0.1",
    cast=Csv(),
)

RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)


# ============================================================
# APPLICATIONS
# ============================================================

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third party
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "django_filters",
    "django_celery_beat",
    "django_extensions",
    # local
    "apps.languages",
    "apps.tenancy",
    "apps.accounts",
    "apps.customers",
    "apps.invoices",
    "apps.payments",
    "apps.comms",
    "apps.collections",
    "apps.ai",
    "apps.voice",
    "apps.webhooks",
    "apps.audit",
    "apps.subscriptions",
    "apps.reports",
]


# ============================================================
# MIDDLEWARE
# ============================================================

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.tenancy.middleware.CurrentOrgMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# ============================================================
# URLS / WSGI
# ============================================================

ROOT_URLCONF = "config.urls"

WSGI_APPLICATION = "config.wsgi.application"


# ============================================================
# TEMPLATES
# ============================================================

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            BASE_DIR / "templates",
        ],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


# ============================================================
# DATABASE
# ============================================================

DATABASE_URL = config("DATABASE_URL", default="")

if DATABASE_URL:
    parsed = urlparse(DATABASE_URL)

    # Safely extract port — handle malformed URLs gracefully
    try:
        db_port = parsed.port or 5432
    except ValueError:
        db_port = 5432

    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.lstrip("/"),
            "USER": parsed.username,
            "PASSWORD": parsed.password,
            "HOST": parsed.hostname,
            "PORT": db_port,
            "OPTIONS": {
                "sslmode": "require",
            },
        }
    }

else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


# ============================================================
# CUSTOM USER MODEL
# ============================================================

AUTH_USER_MODEL = "accounts.User"


# ============================================================
# PASSWORD VALIDATION
# ============================================================

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

if DEBUG:
    PASSWORD_HASHERS = [
        "django.contrib.auth.hashers.MD5PasswordHasher",
        "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    ]
else:
    # Production hardening (behind Render's TLS proxy)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)
    SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=31536000, cast=int)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"


# ============================================================
# INTERNATIONALIZATION
# ============================================================

LANGUAGE_CODE = "en-ng"
TIME_ZONE = config("TIME_ZONE", default="Africa/Lagos")
USE_I18N = True
USE_TZ = True


# ============================================================
# STATIC FILES
# ============================================================

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Only include the global static dir if it actually exists. Git does not track
# empty directories, so on Render this folder is absent and listing it produces
# a staticfiles.W004 warning on every management command.
STATICFILES_DIRS = []
if (BASE_DIR / "static").is_dir():
    STATICFILES_DIRS.append(BASE_DIR / "static")


# ============================================================
# MEDIA FILES
# ============================================================

MEDIA_URL = "/media/"

MEDIA_ROOT = BASE_DIR / "media"


# ============================================================
# CORS
# ============================================================

CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default=(
        "http://localhost:5173,"
        "http://127.0.0.1:5173,"
        "http://localhost:3000,"
        "http://127.0.0.1:3000,"
        "http://localhost:8080,"
        "http://127.0.0.1:8080"
    ),
    cast=Csv(),
)

CORS_ALLOW_CREDENTIALS = True

CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^http://localhost(:\d+)?$",
    r"^http://127\.0\.0\.1(:\d+)?$",
]

CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
    "x-org-id",
    "x-org-language",
]

CORS_URLS_REGEX = r"^/(api|health)/.*$"


# ============================================================
# FRONTEND URL
# ============================================================

FRONTEND_URL = config(
    "FRONTEND_URL",
    default="http://localhost:5173",
)


# ============================================================
# REST FRAMEWORK
# ============================================================

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ("rest_framework_simplejwt.authentication.JWTAuthentication",),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_FILTER_BACKENDS": ("django_filters.rest_framework.DjangoFilterBackend", "rest_framework.filters.SearchFilter", "rest_framework.filters.OrderingFilter"),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.UserRateThrottle", "rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"user": "2000/min", "anon": "500/min", "auth": "100/min"},
    # Our API uses ?format=csv/pdf for report exports. Disable DRF's
    # URL format override (default 'format') or it 404s those requests.
    "URL_FORMAT_OVERRIDE": None,
    "EXCEPTION_HANDLER": "apps.tenancy.exceptions.custom_exception_handler",
}

SIMPLE_JWT = {
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}


# ============================================================
# LOGGING
# ============================================================

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "{levelname} {asctime} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "apps": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}


# ============================================================
# CELERY
# ============================================================

CELERY_BROKER_URL = config(
    "CELERY_BROKER_URL",
    default="redis://localhost:6379/0",
)

CELERY_RESULT_BACKEND = config(
    "CELERY_RESULT_BACKEND",
    default="redis://localhost:6379/1",
)

CELERY_ACCEPT_CONTENT = [
    "json",
]

CELERY_TASK_SERIALIZER = "json"

CELERY_RESULT_SERIALIZER = "json"

CELERY_TIMEZONE = TIME_ZONE

CELERY_BEAT_SCHEDULER = (
    "django_celery_beat.schedulers:DatabaseScheduler"
)


# ============================================================
# EMAIL
# ============================================================

DEFAULT_FROM_EMAIL = config(
    "DEFAULT_FROM_EMAIL",
    default="noreply@collectnaija.com",
)

EMAIL_BACKEND = config(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)


# ============================================================
# COMMUNICATION PROVIDERS
# ============================================================

WHATSAPP_PROVIDER = config(
    "WHATSAPP_PROVIDER",
    default="mock",
)

VOICE_PROVIDER = config(
    "VOICE_PROVIDER",
    default="mock",
)

EMAIL_PROVIDER = config(
    "EMAIL_PROVIDER",
    default="auto",
)


# ============================================================
# AFRICA'S TALKING
# ============================================================

AFRICASTALKING_USERNAME = config(
    "AFRICASTALKING_USERNAME",
    default="",
)

AFRICASTALKING_API_KEY = config(
    "AFRICASTALKING_API_KEY",
    default="",
)


# ============================================================
# PAYSTACK
# ============================================================

PAYSTACK_SECRET_KEY = config(
    "PAYSTACK_SECRET_KEY",
    default="",
)

PAYSTACK_PUBLIC_KEY = config(
    "PAYSTACK_PUBLIC_KEY",
    default="",
)

PAYSTACK_WEBHOOK_SECRET = config(
    "PAYSTACK_WEBHOOK_SECRET",
    default="",
)


# ============================================================
# SECURITY SETTINGS
# ============================================================

if DEBUG:
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False

else:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

    CSRF_TRUSTED_ORIGINS = config(
        "CSRF_TRUSTED_ORIGINS",
        default="",
        cast=Csv(),
    )

INTERNAL_IPS = [
    "127.0.0.1",
]
