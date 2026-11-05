"""
Django settings for carmel_project.

Todas as configurações sensíveis vêm do arquivo .env (veja .env.example).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Segurança
# ---------------------------------------------------------------------------
DEBUG = env_bool("DJANGO_DEBUG", True)

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError("Defina DJANGO_SECRET_KEY no .env para rodar com DJANGO_DEBUG=false.")
    SECRET_KEY = "dev-only-insecure-key-carmel-treinamentos"

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1", "carmel-treinamentos.onrender.com")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

if not DEBUG:
    SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", True)
    CSRF_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", True)
    SECURE_CONTENT_TYPE_NOSNIFF = True

# ---------------------------------------------------------------------------
# Aplicação
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "treinamentos.apps.TreinamentosConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "carmel_project.urls"

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
                "treinamentos.context_processors.access",
            ],
        },
    },
]

WSGI_APPLICATION = "carmel_project.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "data" / "db.sqlite3",
        # Pipeline roda em threads: aumenta a tolerância a locks do SQLite.
        "OPTIONS": {"timeout": 20},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 6}},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Fortaleza"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "data" / "staticfiles"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Pipeline de treinamentos
# ---------------------------------------------------------------------------
TEMP_DOCS_DIR = BASE_DIR / "data" / "temp_docs"
MOCK_DRIVE_DIR = BASE_DIR / "data" / "mock_drive"
ALLOWED_DOC_EXTENSIONS = (".pdf", ".docx", ".txt", ".md")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))
# True: o gestor revisa/aprova o roteiro antes de gastar crédito da HeyGen. False: envio automático.
REQUIRE_SCRIPT_REVIEW = env_bool("REQUIRE_SCRIPT_REVIEW", True)
# Como o vídeo é gerado depois da aprovação do roteiro:
#   "manual": o portal espera ("Aguardando Vídeo"); o vídeo é gerado fora (MCP da HeyGen ou site) e registrado depois.
#   "api":    o portal chama a API da HeyGen sozinho (exige saldo de API).
HEYGEN_GENERATION_MODE = os.getenv("HEYGEN_GENERATION_MODE", "manual").strip().lower()
MAX_VIDEO_MB = int(os.getenv("MAX_VIDEO_MB", "500"))

HEYGEN_API_URL = os.getenv("HEYGEN_API_URL", "https://api.heygen.com").rstrip("/")
HEYGEN_POLL_INTERVAL_SECONDS = int(os.getenv("HEYGEN_POLL_INTERVAL_SECONDS", "20"))
HEYGEN_POLL_TIMEOUT_MINUTES = int(os.getenv("HEYGEN_POLL_TIMEOUT_MINUTES", "30"))

GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "data/service_account.json")
DRIVE_SYNC_INTERVAL_MINUTES = int(os.getenv("DRIVE_SYNC_INTERVAL_MINUTES", "5"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "[{asctime}] {levelname} {name}: {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "loggers": {
        "treinamentos": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},
    },
}
