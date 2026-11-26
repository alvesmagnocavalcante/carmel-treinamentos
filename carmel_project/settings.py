"""
Django settings for carmel_project.

Todas as configurações sensíveis vêm do arquivo .env (veja .env.example).
"""

import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

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

ALLOWED_HOSTS = env_list(
    "DJANGO_ALLOWED_HOSTS",
    "localhost,127.0.0.1,carmel-treinamentos.onrender.com",
    "3.139.238.73:10000"
)
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

if not DEBUG:
    SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", True)
    CSRF_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", True)
    SECURE_CONTENT_TYPE_NOSNIFF = True

# ---------------------------------------------------------------------------
# Aplicação
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "treinamentos.apps.CarmelAdminConfig",  # Admin do Django com o painel da Carmel
    "django.forms",  # permite trocar modelos de campos de formulário (ex.: o campo de senha do admin)
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

def database_from_url(url: str) -> dict:
    """Converte DATABASE_URL (postgres://usuario:senha@host:porta/banco?sslmode=require) em config do Django."""
    parsed = urlparse(url)
    if parsed.scheme not in ("postgres", "postgresql"):
        raise RuntimeError("DATABASE_URL precisa começar com postgres:// (PostgreSQL).")
    options = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed.path.lstrip("/")),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": parsed.port or "",
        "OPTIONS": options,
        "CONN_MAX_AGE": 60,
    }


# DATABASE_URL definida: usa o PostgreSQL (ex.: Aiven). Vazia: SQLite local em data/db.sqlite3.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if DATABASE_URL:
    DATABASES = {"default": database_from_url(DATABASE_URL)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "data" / "db.sqlite3",
            # Pipeline roda em threads: aumenta a tolerância a locks do SQLite.
            "OPTIONS": {"timeout": 20},
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "treinamentos.validators.PasswordPolicyValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Fortaleza"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "data" / "staticfiles"

FORM_RENDERER = "django.forms.renderers.TemplatesSetting"

AUTHENTICATION_BACKENDS = ["treinamentos.backends.CpfModelBackend"]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Pipeline de treinamentos
# ---------------------------------------------------------------------------
TEMP_DOCS_DIR = BASE_DIR / "data" / "temp_docs"
ALLOWED_DOC_EXTENSIONS = (".pdf", ".docx", ".txt", ".md")
# True: o gestor revisa/aprova o roteiro antes de gastar crédito da HeyGen. False: envio automático.
REQUIRE_SCRIPT_REVIEW = env_bool("REQUIRE_SCRIPT_REVIEW", True)
MAX_VIDEO_MB = int(os.getenv("MAX_VIDEO_MB", "500"))
# Imagens das cenas (subpasta Imagens do Drive): tamanho máximo e validade do link temporário dado à HeyGen.
MAX_IMAGE_MB = int(os.getenv("MAX_IMAGE_MB", "10"))
IMAGE_URL_TTL_MINUTES = int(os.getenv("IMAGE_URL_TTL_MINUTES", "120"))
# Cenas com imagem animada por IA (cada uma é uma geração a mais na HeyGen): máximo por vídeo, para não gastar sem querer.
# Cadastro feito pela própria pessoa: valida CPF + data de nascimento na Humand (só leitura) e libera o acesso na hora.
SIGNUP_ENABLED = os.getenv("SIGNUP_ENABLED", "true").lower() in ("1", "true", "yes")
# tolera aspas, espaços e o prefixo "Basic" colados junto com a chave (erro comum ao copiar para o painel do Render)
HUMAND_API_KEY = os.getenv("HUMAND_API_KEY", "").strip().strip("\"'").strip().removeprefix("Basic ").strip()
HUMAND_BASE_URL = os.getenv("HUMAND_BASE_URL", "https://api-prod.humand.co/public/api/v1").rstrip("/")
SIGNUP_MAX_ATTEMPTS = int(os.getenv("SIGNUP_MAX_ATTEMPTS", "5"))      # tentativas erradas por IP/CPF...
SIGNUP_LOCK_MINUTES = int(os.getenv("SIGNUP_LOCK_MINUTES", "15"))     # ...dentro desta janela
MAX_ANIMATED_SCENES = int(os.getenv("MAX_ANIMATED_SCENES", "4"))
# Fidelidade da animação: clipe curto (5 s é o mínimo da HeyGen; a narração mais longa repete o clipe em ciclo) e o
# último quadro preso à imagem original (endImage), para a IA não ir se afastando da foto.
ANIMATION_CLIP_SECONDS = int(os.getenv("ANIMATION_CLIP_SECONDS", "5"))
ANIMATION_LOCK_END_FRAME = env_bool("ANIMATION_LOCK_END_FRAME", True)
PORTAL_BASE_URL = os.getenv("PORTAL_BASE_URL", "").strip().rstrip("/")  # vazio = usa o endereço da requisição

# Conector MCP do portal (para o Claude): vazio = conector desligado.
MCP_TOKEN = os.getenv("MCP_TOKEN", "").strip()
# Só links de vídeo destes domínios são baixados pelo conector (evita que o servidor busque URLs arbitrárias).
MCP_ALLOWED_VIDEO_HOSTS = env_list("MCP_ALLOWED_VIDEO_HOSTS", "heygen.ai,heygen.com")

GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "data/service_account.json")
# Alternativa ao arquivo: conteúdo do JSON da conta de serviço (útil no Cloud Run, via Secret Manager).
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
DRIVE_SYNC_INTERVAL_MINUTES =int(os.getenv("DRIVE_SYNC_INTERVAL_MINUTES", "5"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "[{asctime}] {levelname} {name}: {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "loggers": {
        "treinamentos": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},
    },
}
