# CLAUDE.md — ummvva-bot

> Этот файл читается в НАЧАЛЕ каждой сессии. Здесь — продукт, стек, архитектура и
> незыблемые правила. Журнал работы между сессиями — в `progress.md`.

## Правило работы с progress.md (соблюдай ВСЕГДА)
1. В НАЧАЛЕ каждой сессии — прочитай `progress.md`, чтобы понять контекст.
2. В КОНЦЕ каждой сессии — обнови `progress.md`: перенеси выполненное в
   «Завершённые промпты», поставь следующий в «Текущий промпт», отметь чекбоксы,
   запиши важные решения и проблемы.
3. progress.md — журнал между сессиями. Не теряй его, не перезаписывай целиком,
   только дополняй.

## О продукте
- **Название:** ummvva-bot (отдельный продукт, НЕ связан с платформой ummvva-app).
- **Что это:** WhatsApp-бот, который отвечает клиентам стоматологии 24/7, когда
  менеджеры не на связи. Знает услуги, цены, время работы клиники. Не продаёт
  агрессивно — даёт информацию и помогает оставить заявку на запись.
- **Аудитория:** стоматологии в Казахстане. Продаётся как SaaS многим клиникам.
- **Боль, которую решаем:** клиент пишет ночью, ответить некому, он уходит к
  конкуренту.
- **Бизнес-модель:** месячный тариф на клинику.

## Стек (СТРОГО используй именно это)
- **Backend:** Django + Django REST Framework, Python 3.12
- **БД:** PostgreSQL
- **Очередь:** Celery + Redis (обработка входящих сообщений асинхронно)
- **Админка:** стандартный Django admin (НЕ строим отдельный фронтенд)
- **AI:** Groq API (текст + Whisper для голоса), OpenAI-совместимый SDK
- **Деплой:** Docker + docker-compose
- **Менеджер пакетов:** pip + requirements.txt

## Архитектура (КРИТИЧНО)
1. **Мультитенант.** Один сервер обслуживает много клиник. Модель `Clinic`. У всех
   таблиц с данными клиник ОБЯЗАТЕЛЬНО есть `clinic_id`. Маршрутизация входящих —
   по номеру-получателю WhatsApp.

2. **Абстракция провайдеров — незыблемое правило.** Никогда не вызывай WhatsApp или
   AI напрямую из бизнес-логики. Всегда через интерфейс:
   - `providers/whatsapp/base.py` — абстрактный класс `WhatsAppProvider` с методами
     `send_message(to, text)`, `download_media(media_id)`. Реализации: `mock`
     (тесты без интернета), `evolution` (Evolution API для MVP), `meta`
     (Cloud API для прода). Выбор — через `WHATSAPP_PROVIDER`. Фабрика:
     `providers/whatsapp/factory.py::get_whatsapp_provider()`.
   - `providers/ai/base.py` — абстрактный класс `AIProvider` с методами
     `generate(messages, clinic)`, `transcribe(audio_bytes, language)`. Реализации:
     `mock`, `groq`, `gemini`. Выбор — через `AI_PROVIDER`. Фабрика:
     `providers/ai/factory.py::get_ai_provider()`.

3. **Поток обработки сообщения:**
   webhook принимает входящее → ставит задачу в Celery → worker определяет клинику
   по номеру → собирает системный промпт из данных клиники → подгружает историю
   последних 10 сообщений → вызывает `AIProvider.generate()` → отправляет ответ
   через `WhatsAppProvider.send_message()`.

4. **«Обучение» под клинику — это НЕ файнтюнинг.** Данные клиники (услуги, цены,
   часы, адрес, FAQ, тон) подаются в системный промпт. Модель не дообучается.

## Данные пациентов
Это медицинская сфера (закон РК «О персональных данных», особая категория).
Не логируй лишнего, переписки шифруй на уровне БД/диска, согласие на обработку —
отдельным полем у клиента.

## Структура проекта
```
ummvva-bot/
├── CLAUDE.md                 # этот файл (читать в начале сессии)
├── progress.md               # журнал между сессиями (обновлять в конце сессии)
├── .env.example              # все переменные окружения
├── requirements.txt
├── Dockerfile
├── docker-compose.yml        # db (postgres) + redis + web + worker
├── manage.py
├── config/                   # Django-проект
│   ├── settings.py           # читает всё из окружения
│   ├── urls.py               # admin/, health/
│   ├── celery.py             # Celery app
│   ├── wsgi.py / asgi.py
├── clinics/                  # приложение с моделью Clinic
│   ├── models.py             # Clinic (корень мультитенантности)
│   ├── admin.py
│   └── migrations/
└── providers/                # абстракции провайдеров (НЕ вызывать API напрямую!)
    ├── whatsapp/  base.py · mock.py · factory.py
    └── ai/        base.py · mock.py · factory.py
```

## Как запускать
```bash
cp .env.example .env          # затем заполнить ключи
docker compose up --build     # поднимет db, redis, web (миграции + gunicorn), worker
# админка: http://localhost:8000/admin/  (создать суперюзера командой ниже)
docker compose exec web python manage.py createsuperuser
```
Локальные команды управления: `docker compose exec web python manage.py <cmd>`.

## Evolution API (WhatsApp для MVP)
Реализация: `providers/whatsapp/evolution.py::EvolutionWhatsAppProvider`. Включается
через `WHATSAPP_PROVIDER=evolution` + три ENV: `EVOLUTION_API_URL`, `EVOLUTION_API_KEY`,
`EVOLUTION_INSTANCE`. По умолчанию остаётся `mock` (тесты без интернета).

**Как поднять (локально):**
1. Запустить Evolution API в Docker (отдельный сервис рядом с нашим compose):
   ```bash
   docker run -d --name evolution -p 8080:8080 \
     -e AUTHENTICATION_API_KEY=<your-global-key> \
     atendai/evolution-api:latest
   ```
   (для прода — постоянные тома + Postgres/Redis по доке Evolution).
2. Создать инстанс (имя = `EVOLUTION_INSTANCE`):
   ```bash
   curl -X POST http://localhost:8080/instance/create \
     -H "apikey: <your-global-key>" -H "Content-Type: application/json" \
     -d '{"instanceName":"clinic1","integration":"WHATSAPP-BAILEYS"}'
   ```
3. Привязать номер по QR: открыть `http://localhost:8080/instance/connect/clinic1`
   (или дёрнуть тот же endpoint) → отсканировать QR из WhatsApp на телефоне клиники
   (Связанные устройства).
4. Прописать webhook на наш приёмник входящих (URL поставим в Промпте #5,
   когда появится эндпоинт `/webhook/whatsapp/`):
   ```bash
   curl -X POST http://localhost:8080/webhook/set/clinic1 \
     -H "apikey: <your-global-key>" -H "Content-Type: application/json" \
     -d '{"webhook":{"enabled":true,"url":"https://<наш-хост>/webhook/whatsapp/",
          "events":["MESSAGES_UPSERT"]}}'
   ```
5. Заполнить `.env` (`EVOLUTION_API_URL`, `EVOLUTION_API_KEY`, `EVOLUTION_INSTANCE`),
   выставить `WHATSAPP_PROVIDER=evolution`, перезапустить web/worker.

Отправка: `POST {URL}/message/sendText/{instance}` с заголовком `apikey` и телом
`{"number","text"}`. `download_media` — заглушка (NotImplementedError) до Фазы 2.

## Дорожная карта (фазы)
- [x] **Фаза 0** — Каркас: Django + Celery + Postgres + mock-провайдеры + Clinic
- [ ] **Фаза 1** — Текстовый бот на одну клинику (реальный Groq, webhook, обработка)
- [ ] **Фаза 2** — Голосовые сообщения (Whisper через Groq)
- [ ] **Фаза 3** — Заявки на запись + уведомление менеджера
- [ ] **Фаза 4** — Мультитенант (много клиник на одном сервере)
- [ ] **Фаза 5** — Биллинг (месячный тариф)
- [ ] **Фаза 6** — Прод (Meta Cloud API, деплой, мониторинг)

## Заявки на запись (Фаза 3) — ГЛАВНОЕ ПРАВИЛО
**Бот НИКОГДА не подтверждает приём сам и не пишет в чужой календарь.** Он только
СОБИРАЕТ заявку (услуга, желаемые дата/время, контакт пациента) и ПЕРЕДАЁТ её
менеджеру клиники. Подтверждение/отказ/перенос — всегда решение человека.
- Заявки живут в приложении `bookings`, модель `BookingRequest` (FK на `Clinic` —
  мультитенант, и на `Conversation` через `SET_NULL`).
- ПДн пациента (`customer_phone`, `customer_name`) шифруются на уровне поля
  (`EncryptedCharField`), как `Message.content`. Услугу/дату/время НЕ шифруем
  (не ПДн, удобно фильтровать в admin).
- Статусы заявки: `new` → `notified` → `confirmed` / `rejected` / `cancelled`.
- Куда уведомлять менеджера — `Clinic.manager_whatsapp` (+ флаг
  `Clinic.notifications_enabled`). Уведомление идёт через абстракцию
  `WhatsAppProvider`, не напрямую.

## Незыблемые правила (повторно — не нарушать)
- Только заявленный стек. Без React-фронта — только Django admin.
- Любой вызов WhatsApp/AI — только через абстракцию провайдеров и фабрику.
- Любая таблица с данными клиники имеет `clinic_id`.
- Реальные API подключаются по фазам; по умолчанию провайдеры = `mock`.
- Персональные/медицинские данные — минимум логов, шифрование, поле согласия.
- **Фаза 3: бот не подтверждает запись сам — только собирает заявку и передаёт
  менеджеру** (см. раздел «Заявки на запись»).
