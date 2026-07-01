"""Configuration Django du service AI Commerce Assistant."""
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "unsafe-development-key")
DEBUG = os.getenv("DJANGO_DEBUG", "False").lower() in {"1", "true", "yes"}
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv(
        "DJANGO_ALLOWED_HOSTS",
        "localhost,127.0.0.1,.ngrok-free.dev,.ngrok-free.app,.ngrok.app",
    ).split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "rest_framework",
    "commerce",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "ai_commerce.urls"
TEMPLATES = []
WSGI_APPLICATION = "ai_commerce.wsgi.application"

database_url = os.getenv("DATABASE_URL", "").strip()
if database_url:
    parsed_database = urlparse(database_url)
    default_database_port = (
        6543
        if str(parsed_database.hostname or "").endswith(".pooler.supabase.com")
        else (parsed_database.port or 5432)
    )
    database_port = int(os.getenv("DB_PORT", default_database_port))
    database_options = {"sslmode": os.getenv("DB_SSLMODE", "require")}
    if database_port == 6543:
        # Supavisor en mode transaction ne prend pas en charge les requêtes préparées.
        database_options["prepare_threshold"] = None
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(parsed_database.path.lstrip("/")),
            "USER": unquote(parsed_database.username or ""),
            "PASSWORD": unquote(parsed_database.password or ""),
            "HOST": parsed_database.hostname or "",
            "PORT": database_port,
            "CONN_MAX_AGE": 60,
            "OPTIONS": database_options,
        }
    }
else:
    # SQLite reste disponible pour le développement et les tests locaux.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

USE_TZ = True
LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Africa/Dakar"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
N8N_API_TOKEN = os.getenv("N8N_API_TOKEN", "").strip()
COMMERCE_RATE_LIMIT = int(os.getenv("COMMERCE_RATE_LIMIT", "60"))

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "commerce-api-rate-limit",
    }
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
    "EXCEPTION_HANDLER": "commerce.exception_handler.json_exception_handler",
}
