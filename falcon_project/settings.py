from pathlib import Path
import os
import shlex
from decimal import Decimal
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env", override=True)


def env_str(key, default=""):
    return os.environ.get(key, default)


def env_bool(key, default=False):
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(key, default=0):
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def env_list(key, default=None):
    raw = os.environ.get(key)
    if raw is None:
        return list(default or [])
    return [item.strip() for item in shlex.split(raw) if item.strip()]


SECRET_KEY = env_str("SECRET_KEY", "django-insecure-dev-key")
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "crispy_forms",
    "crispy_bootstrap5",
    "apps.core",
    "apps.audit",
    "apps.accounts",
    "apps.marketplace",
    "apps.vendor",
    "apps.delivery",
    "apps.parcel",
    "apps.reports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "falcon_project.urls"

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
                "apps.core.context_processors.falcon_context",
            ],
        },
    },
]

WSGI_APPLICATION = "falcon_project.wsgi.application"


def _database_from_url(url):
    parsed = urlparse(url or "")
    if parsed.scheme.startswith("sqlite"):
        name = parsed.path.lstrip("/") if parsed.path else "db.sqlite3"
        path = Path(name)
        if not path.is_absolute():
            path = BASE_DIR / path
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str(path),
        }
    if parsed.scheme.startswith("postgres"):
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.lstrip("/"),
            "USER": parsed.username or "",
            "PASSWORD": parsed.password or "",
            "HOST": parsed.hostname or "",
            "PORT": parsed.port or 5432,
        }
    raise ValueError(f"Unsupported DATABASE_URL scheme: {parsed.scheme!r}")


DATABASES = {
    "default": _database_from_url(
        env_str("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}")
    )
}

AUTH_USER_MODEL = "accounts.FalconUser"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Lagos"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if not DEBUG
        else "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

LOGIN_URL = "/login/"

EMAIL_BACKEND = (
    "django.core.mail.backends.smtp.EmailBackend"
    if env_str("EMAIL_BACKEND", "").strip().lower() == "smtp"
    else "django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = env_str("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = env_int("EMAIL_PORT", 587)
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_HOST_USER = env_str("EMAIL_HOST_USER")
# Gmail App Passwords are 16 chars; Google displays them with cosmetic
# spaces ("abcd efgh ijkl mnop") which must not be sent to the server.
EMAIL_HOST_PASSWORD = env_str("EMAIL_HOST_PASSWORD").strip().replace(" ", "")
DEFAULT_FROM_EMAIL = env_str(
    "DEFAULT_FROM_EMAIL", f"Falcon Delivery Service <{EMAIL_HOST_USER or 'no-reply@falcon.test'}>"
)

PAYSTACK_SECRET_KEY = env_str("PAYSTACK_SECRET_KEY")
PAYSTACK_PUBLIC_KEY = env_str("PAYSTACK_PUBLIC_KEY")
PAYSTACK_BASE_URL = "https://api.paystack.co"

GOOGLE_MAPS_API_KEY = env_str("GOOGLE_MAPS_API_KEY")

WITHDRAWAL_FEE = Decimal("250.00")
OTP_EXPIRY_MINUTES = 10

MESSAGE_TAGS = {
    "debug": "debug",
    "info": "info",
    "success": "success",
    "warning": "warning",
    "error": "error",
}
