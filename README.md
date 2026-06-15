# ummvva-bot

WhatsApp AI-ассистент для стоматологий. Принимает сообщения пациентов 24/7 — когда менеджеры не на связи — отвечает на вопросы об услугах, ценах и часах работы, помогает оставить заявку на запись. Поддерживает русский и казахский языки.

Продаётся как SaaS: один сервер, много клиник, плоская месячная подписка.

## Возможности

- Текстовый бот: отвечает по данным конкретной клиники (услуги, цены, часы, FAQ)
- Голосовые сообщения: транскрипция через Whisper, ответ текстом
- Запись на приём: бот собирает заявку (услуга / дата / время), отправляет менеджеру — подтверждение только от человека
- Мультитенантность: данные клиник изолированы, маршрутизация по инстансу Evolution
- Биллинг: пробный период, подписка, grace-период, ежедневный beat-цикл, кабинет клиники в Django admin

## Архитектура

**LLM отвечает за язык, Python — за бизнес-правила.**

- Системный промпт строится из данных модели `Clinic` (прайс, часы, FAQ). Файнтюнинга нет.
- Бизнес-валидация — детерминированный Python: `bookings/validation.py` проверяет дату/время слота (прошлое, выходной, вне часов, шаг 30 мин, буфер до закрытия) до отправки заявки.
- Стейт-машина записи живёт на `Conversation.booking_stage`. Заявка создаётся только при явном «да» от пациента; менеджер подтверждает или отклоняет через WhatsApp (`+N` / `-N`) или Django admin.
- Пайплайн: webhook → Celery → резолв клиники → гейт подписки → AI generate → WhatsApp send.
- Шифрование ПДн на уровне поля (`django-fernet-fields-v2`): `Message.content`, `customer_phone`, `customer_name`.

## Стек

| Слой | Технология |
|------|-----------|
| Backend | Python 3.12, Django 5.1, Django REST Framework |
| БД | PostgreSQL 16 |
| Очередь | Celery 5.4 + Redis 7 |
| AI (текст) | Groq `llama-3.3-70b-versatile` |
| AI (голос) | Groq Whisper `whisper-large-v3` |
| WhatsApp | Evolution API v2 |
| Шифрование | `django-fernet-fields-v2` (Fernet/AES) |
| Деплой | Docker Compose |

## Запуск

```bash
# 1. Переменные окружения
cp .env.example .env
# отредактировать .env: GROQ_API_KEY, FIELD_ENCRYPTION_KEY, Evolution-ключи

# 2. Основной стек (db + redis + web + worker + beat)
docker compose up -d --build

# 3. Evolution API (WhatsApp-шлюз)
docker compose -f evolution-compose.yml up -d

# 4. Суперпользователь Django
docker compose exec web python manage.py createsuperuser
```

**Подключить клинику к Evolution:**
1. Открыть http://localhost:8080/manager → войти → создать инстанс
2. Отсканировать QR из WhatsApp (Связанные устройства) — статус станет `"state":"open"`
3. Создать `Clinic` в Django admin, заполнить `instance_name`
4. Прописать webhook инстанса на `https://<хост>/webhook/whatsapp/`

**Admin:** http://localhost:8000/admin/

**После изменений кода** (без пересборки образа):
```bash
docker compose restart worker beat
```

## Переменные окружения

Все переменные в `.env.example` с комментариями. Ключевые:

| Переменная | Описание |
|-----------|---------|
| `FIELD_ENCRYPTION_KEY` | **Критично.** Fernet-ключ шифрования ПДн. Сгенерировать: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `DJANGO_SECRET_KEY` | Django secret key |
| `GROQ_API_KEY` | API-ключ Groq (текст + голос) |
| `WHATSAPP_PROVIDER` | `mock` (тесты) / `evolution` (MVP) / `meta` (прод) |
| `AI_PROVIDER` | `mock` (тесты) / `groq` / `gemini` |
| `EVOLUTION_API_URL` | URL Evolution API (`http://evolution:8080` внутри сети) |
| `EVOLUTION_API_KEY` | Глобальный ключ Evolution (`AUTHENTICATION_API_KEY`) |
| `EVOLUTION_INSTANCE` | Имя инстанса (фолбэк; для мультитенанта — `instance_name` у каждой клиники) |
| `BILLING_PROVIDER` | `manual` (MVP) / `kaspi` (заглушка) |
| `TRIAL_DAYS` | Длительность пробного периода, дней (по умолчанию 14) |
| `GRACE_DAYS` | Грейс после окончания подписки, дней (по умолчанию 3) |
| `OWNER_WHATSAPP` | Номер владельца SaaS для служебных алертов биллинга |

## Структура проекта

```
ummvva-bot/
├── config/               # Django-проект (settings, urls, celery, wsgi)
├── clinics/              # Модель Clinic — корень мультитенантности
├── messaging/            # Webhook, пайплайн обработки, Conversation/Message
│   └── services/         # Сборка системного промпта, история диалога
├── bookings/             # Заявки на запись, стейт-машина, менеджерская ветка
│   ├── extraction.py     # LLM-извлечение слотов из текста
│   ├── flow.py           # Стейт-машина booking_stage
│   └── validation.py     # Детерминированная проверка даты/времени слота
├── billing/              # Подписки, тарифы, usage-учёт, beat-цикл
├── providers/
│   ├── whatsapp/         # Абстракция WhatsApp: mock | evolution | meta
│   ├── ai/               # Абстракция AI: mock | groq | gemini
│   └── billing/          # Абстракция эквайера: manual | kaspi
├── docker-compose.yml    # db + redis + web + worker + beat
├── evolution-compose.yml # Evolution API (WhatsApp-шлюз)
└── .env.example          # Все переменные окружения
```

## Тесты

```bash
# Без Docker — тесты используют SQLite in-memory
pytest

# Внутри контейнера
docker compose exec web pytest
```

133 теста, офлайн (mock-провайдеры).
