"""
Django settings for ummvva-bot.

Конфигурация читается из переменных окружения (см. .env.example).
"""
import os
from pathlib import Path

from celery.schedules import crontab
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Загружаем .env, если он есть (локальная разработка вне Docker).
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "on")


# --- Безопасность ---
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "insecure-dev-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if h.strip()
]

# Ключ шифрования полей БД (медицинские/персональные данные шифруем на уровне поля).
# Используется django-fernet-fields-v2 (settings.FERNET_KEYS). Ключ берём из env
# FIELD_ENCRYPTION_KEY. Если не задан — в dev библиотека откатывается на SECRET_KEY,
# но для прода ОБЯЗАТЕЛЬНО задать отдельный ключ FIELD_ENCRYPTION_KEY.
_field_encryption_key = os.environ.get("FIELD_ENCRYPTION_KEY", "")
if _field_encryption_key:
    FERNET_KEYS = [_field_encryption_key]

# --- Приложения ---
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    # Local
    "clinics",
    "messaging",
    "bookings",
    "billing",
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

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# --- База данных ---
# USE_SQLITE_FOR_TESTS=1 позволяет pytest работать без Docker/Postgres (conftest).
if env_bool("USE_SQLITE_FOR_TESTS"):
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", "ummvva"),
            "USER": os.environ.get("POSTGRES_USER", "ummvva"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "ummvva"),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }

# --- Пароли ---
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Локализация ---
LANGUAGE_CODE = "ru"
TIME_ZONE = "Asia/Almaty"
USE_I18N = True
USE_TZ = True

# --- Статика ---
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Django REST Framework ---
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
}

# --- Celery / Redis ---
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = TIME_ZONE

# Расписание периодических задач (Celery beat). Запускается процессом
# `celery -A config beat` (сервис `beat` в docker-compose).
# Ежедневная проверка подписок: напоминания об оплате, перевод в past_due,
# автосуспенд после грейса. Время — 09:00 по Asia/Almaty (CELERY_TIMEZONE).
CELERY_BEAT_SCHEDULE = {
    "billing-daily-cycle": {
        "task": "billing.tasks.run_billing_cycle",
        "schedule": crontab(hour=9, minute=0),
    },
}

# --- Провайдеры (выбор реализации через окружение) ---
WHATSAPP_PROVIDER = os.environ.get("WHATSAPP_PROVIDER", "mock")
AI_PROVIDER = os.environ.get("AI_PROVIDER", "mock")

# Секрет webhook приёма входящих. Передаётся провайдером в заголовке
# X-Webhook-Token или query-параметре ?token=. Если пуст — проверка пропускается
# (dev, mock). Для прода задать ОБЯЗАТЕЛЬНО и прописать в URL вебхука инстанса.
WHATSAPP_WEBHOOK_TOKEN = os.environ.get("WHATSAPP_WEBHOOK_TOKEN", "")

# Настройки провайдеров (читаются их реализациями).
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_WHISPER_MODEL = os.environ.get("GROQ_WHISPER_MODEL", "whisper-large-v3")
GROQ_TEMPERATURE = float(os.environ.get("GROQ_TEMPERATURE", "0.3"))
# Макс. попыток при 429 / 5xx от AI-провайдера (экспоненциальный backoff).
AI_MAX_RETRIES = int(os.environ.get("AI_MAX_RETRIES", "3"))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

EVOLUTION_API_URL = os.environ.get("EVOLUTION_API_URL", "")
EVOLUTION_API_KEY = os.environ.get("EVOLUTION_API_KEY", "")
EVOLUTION_INSTANCE = os.environ.get("EVOLUTION_INSTANCE", "")

META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN", "")
META_PHONE_NUMBER_ID = os.environ.get("META_PHONE_NUMBER_ID", "")
META_VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN", "")

# Окно дедупликации заявок на запись (минуты). Если за это время от того же диалога
# уже есть заявка со статусом new/notified — обновляем её, не создаём дубль.
BOOKING_DEDUP_MINUTES = int(os.environ.get("BOOKING_DEDUP_MINUTES", "30"))

# --- Биллинг (Фаза 5) ---
# Длительность пробного периода новой клиники в днях (автотриал через сигнал).
TRIAL_DAYS = int(os.environ.get("TRIAL_DAYS", "14"))
# Грейс-период после окончания оплаченного периода до приостановки, в днях.
GRACE_DAYS = int(os.environ.get("GRACE_DAYS", "3"))
# Платёжный провайдер по умолчанию (manual — приём оплат вручную).
BILLING_PROVIDER = os.environ.get("BILLING_PROVIDER", "manual")
# Отправлять ли неоплатившей (suspended) клинике короткое нейтральное уведомление
# «сервис недоступен». AI при этом НЕ вызывается (токены Groq не тратим).
SEND_SUSPENDED_NOTICE = os.environ.get("SEND_SUSPENDED_NOTICE", "true").lower() == "true"
# Тротлинг этого уведомления: не чаще одного раза в N часов на диалог (чтобы не
# спамить пациенту на каждое сообщение). Отметка — на Conversation.suspended_notice_at.
SUSPENDED_NOTICE_THROTTLE_HOURS = int(
    os.environ.get("SUSPENDED_NOTICE_THROTTLE_HOURS", "24")
)
# Номер владельца SaaS (WhatsApp) для служебных алертов биллинга — например,
# мягкое уведомление «клиника превысила лимит сообщений». Опционально: если пусто,
# алерт остаётся только в логах (бота это не трогает).
OWNER_WHATSAPP = os.environ.get("OWNER_WHATSAPP", "").strip()

# --- Логирование (минимально, без персональных данных) ---
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
