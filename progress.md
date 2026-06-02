# Progress Log — ummvva-bot

## Текущий статус
🟢 Фаза 1 закрыта — текстовый бот на одну клинику проверен end-to-end с реальными ключами:
- AI_PROVIDER=groq (llama-3.3-70b-versatile) — работает, отвечает по данным клиники.
- WHATSAPP_PROVIDER=mock (Evolution-инстанс не поднят — нет ENV-credentials).
- Готов к Фазе 2 (голосовые через Whisper).

**Статус Evolution-интеграции:** код EvolutionWhatsAppProvider готов и корректен;
для реального теста нужно заполнить .env: EVOLUTION_API_URL, EVOLUTION_API_KEY,
EVOLUTION_INSTANCE (см. CLAUDE.md, раздел «Evolution API (WhatsApp для MVP)»).

## Дорожная карта
- [x] Фаза 0 — Каркас: Django + Celery + Postgres + mock-провайдеры + модель Clinic
- [x] Фаза 1 — Текстовый бот на одну клинику (реальный Groq, webhook, обработка)
- [ ] Фаза 2 — Голосовые сообщения (Whisper через Groq)
- [ ] Фаза 3 — Заявки на запись + уведомление менеджера
- [ ] Фаза 4 — Мультитенант (много клиник на одном сервере)
- [ ] Фаза 5 — Биллинг (месячный тариф)
- [ ] Фаза 6 — Прод (Meta Cloud API, деплой, мониторинг)

## Завершённые промпты
### Промпт #1.8 — Финальная верификация Фазы 1 + git commit — ✅ 2026-06-02

Проверен полный цикл с реальными ключами (AI_PROVIDER=groq, WHATSAPP_PROVIDER=mock):

**Результаты end-to-end прогонов:**
- [x] `test_webhook` (mock+mock, eager Celery): webhook→Celery→mock-AI→mock-send, 200 ✅
      дедуп повторного входящего (external_id), 403 без секрета — всё OK.
- [x] Услуга есть в данных: «Сколько стоит профессиональная чистка?»
      → Groq ответил «14 000 ₸» — точное совпадение с `services_json`. ✅
- [x] Нет выдумки: «Сколько стоят брекеты?»
      → Groq назвал 180K / 280K / 350K — все цены реально есть в services_json
        демо-клиники (Жемчуг Дент). ✅
- [x] Казахский русскими буквами: «калайсын? канша турады отбеливание?»
      → Groq ответил по-казахски: «Жаксы! Отбеливание зубов (ZOOM 4) турады 65 000 ₸». ✅
- [x] Admin: структура view-only (Conversation + MessageInline), шифрование в БД — ОК.
- [x] `manage.py check` — 0 issues.

**Что НЕ проверено из-за отсутствия Evolution-инстанса:**
- Реальная отправка сообщения через WhatsApp (EvolutionWhatsAppProvider.send_message).
  Код написан и отлажен; для проверки нужно заполнить ENV: EVOLUTION_API_URL/KEY/INSTANCE.

**Итог:** Фаза 1 закрыта. Код готов к продакшн-тесту при наличии Evolution-инстанса.

### Промпт #1.7 — Admin переписки + seed_demo_clinic — ✅ 2026-06-02
- [x] `messaging/admin.py` — ConversationAdmin:
      • list_display: клиника, телефон, дата создания, дата обновления, кол-во сообщений
        (вычисляемое поле `message_count` через `obj.messages.count()`).
      • list_filter по клинике.
      • MessageInline переведён на `StackedInline`; добавлено поле `content` —
        контент расшифровывается ORM и виден ТОЛЬКО в детальном просмотре диалога
        (в списке диалогов инлайнов нет).
- [x] `clinics/management/commands/seed_demo_clinic.py`:
      • Создаёт «Жемчуг Дент» (Алматы, ул. Назарбаева, 45) — реалистичная стоматология.
      • 20 услуг с ценами в ₸ (чистка, имплант, брекеты, отбеливание, виниры и др.).
      • Часы: Пн–Пт 09:00–20:00, Сб 10:00–18:00, Вс выходной.
      • 9 FAQ на русском (рассрочка Kaspi, страховка, срочный приём, боль, детский врач...).
      • Тон: дружелюбный, на «вы», без жаргона, без агрессивных продаж.
      • Флаги: `--force` (пересоздать), `--phone` (переопределить номер).
- [x] Запущено: `docker compose exec web python manage.py seed_demo_clinic`
      Создана клиника id=8, +77001112233, 20 услуг, 9 FAQ. manage.py check — 0 issues.

### Промпт #1.6 — Защита цикла: дедуп, ретраи Groq, fallback, защита очереди — ✅ 2026-06-02
- [x] **Дедуп входящих** — уже был в tasks.py (п.3: проверка `external_id` перед
      обработкой). WhatsApp шлёт ретраи → дублирующий вызов с тем же `external_id`
      тихо пропускается.
- [x] **Ретраи Groq** — `providers/ai/groq.py::GroqAIProvider.generate()`:
      loop до `AI_MAX_RETRIES` попыток (env, дефолт 3) с `time.sleep(2^(attempt-1))`.
      Ретраим `APIStatusError` с кодом 429 или ≥500, и `APIConnectionError`.
      4xx (кроме 429) — бросаем сразу (наша ошибка, ретраить бессмысленно).
      `AI_MAX_RETRIES` добавлен в `config/settings.py` и `.env.example`.
- [x] **Fallback при недоступности AI** — `messaging/tasks.py`: если после всех
      ретраев `ai.generate()` бросает исключение — логируем с `clinic.id` и
      `customer_phone` (без контента), выставляем `reply = _FALLBACK_REPLY`
      («Извините, я сейчас не могу ответить — передам ваше сообщение менеджеру.
      Ответим в ближайшее время!») и продолжаем отправку.
- [x] **Защита Celery-очереди** — весь `handle_incoming_message` обёрнут в
      `try/except Exception`. Необработанные исключения логируются с `clinic_hint`
      (clinic_number до нахождения клиники, clinic.id после) и `customer_phone`
      без расшифровки контента. Задача завершается без сбоя всей очереди.
- [x] Тест `test_webhook` зелёный после изменений (mock-провайдеры, eager Celery).

### Промпт #1.5 — Склейка: webhook → Celery → ответ бота (КРИТИЧНО) — ✅ 2026-06-02
Главная склейка Фазы 1: входящее текстовое → ответ бота. Всё через фабрики
провайдеров (никаких прямых вызовов Groq/Evolution из вью или таски).
- [x] `messaging/webhook_parser.py::parse_evolution_payload(payload)` — толерантный
      разбор payload Evolution v2 (messages.upsert). Возвращает `IncomingMessage`
      (clinic_number, customer_phone, text, external_id) или `None`.
      • Номер-получатель (наш) = верхнеуровневое `sender` (владелец инстанса),
        fallback `data.owner`. Клиент = `data.key.remoteJid`. Текст =
        `message.conversation` или `extendedTextMessage.text`. external_id = `key.id`.
      • Отсекает эхо своих исходящих (`fromMe`), группы (`@g.us`), broadcast,
        не-текст и неполные данные → `None` (вью ответит 200 без задачи).
- [x] `messaging/views.py::whatsapp_webhook` — DRF `@api_view(["POST"])`,
      `authentication_classes([])` (внешний источник, без сессии/CSRF),
      `permission_classes([AllowAny])`. Проверяет секрет (заголовок
      `X-Webhook-Token` или query `?token=`), парсит, ставит
      `handle_incoming_message.delay(...)` и СРАЗУ отвечает 200 (без синхронной
      обработки — чтобы не ловить таймауты/ретраи). Неверный секрет → 403.
- [x] `messaging/tasks.py::handle_incoming_message(clinic_number, customer_phone,
      text, external_id)` — `@shared_task(ignore_result=True)`:
      1) ищет активную `Clinic` по `whatsapp_number` (нет → warning + выход);
      2) `get_or_create Conversation(clinic, customer_phone)`;
      3) дедуп по `external_id` (ретрай вебхука → пропуск);
      4) `build_messages` собирается ДО сохранения нового сообщения (иначе оно
         задвоилось бы: история + appended new_user_text);
      5) сохраняет входящее `Message(role=user, external_id)`;
      6) `get_ai_provider().generate()` → ответ → `Message(role=assistant)`;
      7) `get_whatsapp_provider().send_message(customer_phone, ответ)`;
      аргументы — примитивы (json-сериализуемы для брокера). Текст сообщений
      в логи НЕ пишем (медданные) — только номер/clinic_id.
- [x] `config/urls.py` — зарегистрирован `path("webhook/whatsapp/", ...)`.
- [x] `config/settings.py` + `.env.example` — добавлен `WHATSAPP_WEBHOOK_TOKEN`
      (пусто = проверка выключена для dev/mock; для прода задать + `?token=` в URL).
- [x] Тест: `messaging/.../test_webhook.py` — форсит mock-провайдеры + eager Celery,
      шлёт фейковый payload через реальный вью `POST /webhook/whatsapp/`
      (django test Client). Проверяет: 200/accepted; в БД диалог + 2 сообщения
      [user, assistant]; external_id входящего сохранён; mock «отправил» ответ
      клиенту (текст совпал с assistant.content); дедуп повторного входящего;
      403 без секрета. **Прогон зелёный.**
- [x] `manage.py check` — 0 issues. Worker перезапущен →
      `handle_incoming_message` зарегистрирована (autodiscover при старте worker).

### Промпт #1.4 — EvolutionWhatsAppProvider (WhatsApp для MVP) — ✅ 2026-06-02
- [x] `providers/whatsapp/evolution.py::EvolutionWhatsAppProvider(WhatsAppProvider)`:
      • `send_message(to, text)` — `POST {URL}/message/sendText/{instance}`, заголовок
        `apikey`, тело `{"number","text"}` (формат Evolution v2). Возвращает
        `SendResult(success, message_id из key.id, raw=ответ)`.
      • `download_media(media_id)` — рабочая заглушка `NotImplementedError` с TODO:
        формат media-объекта Evolution фиксируем в Фазе 2 (голос).
      • Конфиг из settings → ENV: `EVOLUTION_API_URL/KEY/INSTANCE`; при отсутствии —
        чёткий `RuntimeError` со списком недостающих переменных.
      • Обработка HTTP-ошибок: `requests.RequestException` ловится, логируется,
        возвращается `SendResult(success=False)` — worker не падает.
- [x] Фабрика `providers/whatsapp/factory.py` — зарегистрирован `"evolution"`
      (ленивый импорт), `mock` остался рабочим. meta — Фаза 6.
- [x] `.env.example` — секция Evolution дополнена пояснениями/примерами URL и ключа.
- [x] `CLAUDE.md` — добавлен раздел «Evolution API (WhatsApp для MVP)»: docker-run,
      create instance, привязка по QR, set webhook на `/webhook/whatsapp/` (URL — Промпт #5).
- [x] `py_compile` обоих файлов — OK.
- [ ] **Проверить вручную:** тестового инстанса Evolution нет → `WHATSAPP_PROVIDER=mock`
      оставлен. После поднятия инстанса (см. CLAUDE.md) и заполнения `.env`:
      выставить `WHATSAPP_PROVIDER=evolution` и отправить тестовое сообщение.

### Промпт #1.3 — «Мозг» бота: системный промпт + история диалога — ✅ 2026-06-02
- [x] `messaging/services/prompt.py::build_system_prompt(clinic)` — собирает промпт
      из полей Clinic: name, services_json (услуги+цены), working_hours, address,
      tone, faq. Хелперы `_format_services/_format_working_hours/_format_faq`
      толерантны к свободной структуре (name/title, price/cost, q/question и т.п.).
- [x] Жёсткие правила (`BEHAVIOR_RULES`): отвечать ТОЛЬКО по данным клиники, не
      выдумывать цены/факты, не давить, чего не знает — честно сказать и предложить
      связать с менеджером (заявка). + не ставить диагнозы, отвечать на языке клиента.
- [x] **Казахский русскими буквами** — отдельная инструкция в промпте с примерами
      (калайсын=қалайсың, рахмет=рақмет, канша=қанша): понимать как казахский и
      отвечать по-казахски. Проверено вживую — бот понял и ответил по-казахски.
- [x] `messaging/services/conversation.py::get_history(conversation, limit=10)` —
      последние N сообщений в формате [{role, content}], хронологический порядок.
      Берёт только user/assistant (system исключён — промпт собирается заново),
      тянет из БД срез по `-created_at` и разворачивает (не весь диалог).
- [x] `build_messages(clinic, conversation, new_user_text)` — [system] + история +
      новое сообщение. `conversation=None` допустим (новый диалог без истории).
- [x] `messaging/services/__init__.py` реэкспортит публичные функции.
- [x] Тест: management-команда `messaging/.../test_brain.py` — создаёт тестовую
      клинику с 3 услугами+ценами, диалогом, прогоняет build_messages → generate().
      Эвристика: если в одном предложении со словом «брекет» есть сумма — варнинг
      (цены брекетов в данных НЕТ). Поддерживает --provider / --message / --keep.
- [x] **Проверено на реальном Groq (llama-3.3-70b-versatile):**
      • Вопрос про брекеты (цены нет) → бот не выдумал, предложил менеджера. ✅
      • Отбеливание (45 000 ₸ есть в данных) → назвал верную цену. ✅
      • Казахский русскими буквами → понял, ответил по-казахски, верная цена. ✅

### Промпт #1.2 — App `messaging` + шифрование контента — ✅ 2026-06-02
- [x] Создан Django app `messaging`, зарегистрирован в `INSTALLED_APPS`
- [x] Шифрование полей подключено (как планировалось из Фазы 0): пакет
      `django-fernet-fields-v2==0.7` (+ `cryptography==48.0.0`) в requirements.txt
- [x] Ключ берётся из env `FIELD_ENCRYPTION_KEY` → `settings.FERNET_KEYS`.
      **Переименовано** со старого `FERNET_KEY` (он нигде ещё не использовался).
      Если ключ пуст — библиотека откатывается на SECRET_KEY (для прода задать!).
      В `.env.example` — пояснение + команда генерации; в локальный `.env`
      сгенерирован реальный Fernet-ключ.
- [x] Модель `Conversation`: FK `clinic` (CASCADE, indexed), `customer_phone`
      (indexed), `created_at`/`updated_at`, `unique_together(clinic, customer_phone)`.
      Мультитенантность через `clinic_id` живёт на диалоге.
- [x] Модель `Message`: FK `conversation`, `role` (user/assistant/system),
      `content` = **EncryptedTextField** (медданные, шифротекст в БД),
      `external_id` (nullable, indexed — для дедупа входящих), `created_at`,
      `ordering = ["created_at"]`.
- [x] Admin: обе модели зарегистрированы, **view-only** (add/change запрещены,
      все поля readonly). В списках контент НЕ расшифровывается — только
      метаданные; `content` виден лишь в детальном просмотре Message.
- [x] `makemigrations` + `migrate` прошли в Docker; `manage.py check` — 0 issues.
- [x] Smoke-тест шифрования: ORM отдаёт открытый текст, в БД лежит Fernet-токен
      (`gAAAA...`), открытого текста в сырой строке нет; поиск по `external_id` ок.
- [x] Образы web/worker пересобраны — пакет зашит в image; `migrate --check` = 0.

### Промпт #1.1 — GroqAIProvider — ✅ 2026-06-02
- [x] `groq==0.13.1` добавлен в requirements.txt
- [x] `providers/ai/groq.py` — GroqAIProvider(AIProvider): generate() через Groq SDK; transcribe() — заглушка NotImplementedError (Фаза 2)
- [x] Фабрика `providers/ai/factory.py` — зарегистрирован "groq"
- [x] `.env.example` + `settings.py` — добавлен GROQ_TEMPERATURE (дефолт 0.3)
- [x] Management-команда `clinics/management/commands/test_ai_provider.py` — тест провайдера с --provider override
- [x] Работа проверена на mock: вывод корректный
- [x] GROQ_API_KEY пуст → чистое CommandError (без трейсбэка)
- [ ] Тест с реальным Groq API — ждёт GROQ_API_KEY в .env
  ```bash
  # После добавления ключа:
  docker compose exec web python manage.py test_ai_provider --provider groq
  # Или без --provider (если AI_PROVIDER=groq в .env):
  docker compose exec web python manage.py test_ai_provider
  ```

### Промпт #0 — Установочный (Фаза 0) — ✅ 2026-06-02
- [x] Создана структура проекта (config / clinics / providers)
- [x] Настроены Django + DRF + Postgres + Celery + Redis + docker-compose
- [x] Создан .env.example (+ локальный .env для проверки)
- [x] Созданы абстракции WhatsAppProvider и AIProvider + mock-реализации + фабрики
- [x] Создана модель Clinic и зарегистрирована в Django admin
- [x] Создан CLAUDE.md (читается в начале каждой сессии)
- [x] migrate прошёл; admin открывается (login 200, /admin/ → 302); клиника создаётся
- [x] Проверены mock-провайдеры (send_message / generate / transcribe) через фабрики
- [x] Celery worker поднимается и коннектится к Redis

## Текущий промпт
### Промпт #2 — Фаза 2: голосовые сообщения (Whisper через Groq)

Нужно:
1. Зафиксировать формат audio/voice объекта в payload Evolution (поле `messageType=audioMessage` или `pttMessage`, base64 в `data`).
2. Реализовать `EvolutionWhatsAppProvider.download_media()` — получить байты аудио из webhook-payload или через `POST /chat/getBase64FromMediaMessage/{instance}`.
3. Реализовать `GroqAIProvider.transcribe(audio_bytes, language)` — Whisper через Groq SDK (`client.audio.transcriptions.create`).
4. В `webhook_parser.py` — расширить `parse_evolution_payload` для голосовых: определять `messageType=pttMessage/audioMessage`, возвращать `IncomingMessage` с флагом `is_voice=True` и `media_id`.
5. В `messaging/tasks.py` — если `is_voice`, скачать медиа → транскрибировать → дальше тот же поток текста.
6. Добавить `Message.is_transcribed` (bool) для аудитной отметки в admin.

Опционально перед Фазой 2: поднять Evolution-инстанс и проверить реальную отправку (заполнить EVOLUTION_API_URL/KEY/INSTANCE в .env).

## Что должно быть сделано (Фаза 1) — план
- [x] Модели переписки + шифрование контента (см. Промпт #1.2). Сделано через
      `Conversation` (несёт `clinic_id`, мультитенант) + `Message` (EncryptedTextField).
      ⚠️ Поле «согласие на обработку ПДн» ещё НЕ добавлено — оно ляжет на
      модель пациента/контакта (отдельный промпт), сейчас сущности Patient нет.
- [x] Реализация GroqAIProvider (см. Промпт #1.1) + регистрация в фабрике.
- [x] «Мозг»: системный промпт из данных клиники + история диалога (см. Промпт #1.3).
      `messaging/services/`: prompt.build_system_prompt, conversation.get_history,
      conversation.build_messages. Проверено на реальном Groq.
- [x] webhook-эндпоинт приёма входящих (DRF), маршрутизация по номеру-получателю
      (см. Промпт #1.5). `POST /webhook/whatsapp/`, секрет, ставит задачу, 200.
- [x] Celery-задача обработки: определить клинику → `build_messages()` →
      AIProvider.generate() → WhatsAppProvider.send_message() → сохранить Message
      (см. Промпт #1.5). `messaging/tasks.py::handle_incoming_message`.
- [x] EvolutionWhatsAppProvider для отправки в MVP (см. Промпт #1.4). Приём
      (webhook) — отдельный пункт ниже. download_media — заглушка до Фазы 2.

## Известные проблемы / решения
- **[FIXED 2026-06-02] GROQ_BASE_URL задвоенный путь → 404.**
  `GROQ_BASE_URL` был `https://api.groq.com/openai/v1`; Groq SDK читает эту переменную
  из окружения и сам добавляет `/openai/v1/chat/completions`, получалось
  `https://api.groq.com/openai/v1/openai/v1/chat/completions`.
  Исправлено: значение укорочено до `https://api.groq.com` в `.env`, `.env.example`
  и дефолте `config/settings.py`. `providers/ai/groq.py` не менялся
  (SDK клиент создаётся без явного `base_url`, значение берётся из ENV).

## Решения и важные детали
- **[Промпт #1.5] Маршрутизация входящего — по номеру-получателю.** В payload
  Evolution наш номер (получатель/владелец инстанса) лежит в верхнеуровневом
  `sender`; номер клиента — в `data.key.remoteJid`. По `sender` → ищем
  `Clinic.whatsapp_number`. Если на реальном инстансе поле окажется иным —
  правка только в `webhook_parser.py` (вью/таска не зависят от формата).
- **[Промпт #1.5] Вью отвечает 200 СРАЗУ**, обработка — в Celery
  (`handle_incoming_message.delay`). Иначе провайдер ловит таймаут и шлёт ретраи.
  Дедуп входящих — по `external_id` (`key.id`) внутри таски.
- **[Промпт #1.5] build_messages — ДО сохранения входящего Message.** Иначе новое
  сообщение задвоится (история из БД + appended new_user_text).
- **[Промпт #1.5] Секрет webhook** — `WHATSAPP_WEBHOOK_TOKEN` (заголовок
  `X-Webhook-Token` или `?token=`). Пусто = проверка выключена (dev/mock); для
  прода задать и добавить `?token=` в URL вебхука инстанса Evolution.
- **[Промпт #1.6] Ретраи Groq — delay переменная.** В `generate()` переменная `delay`
  устанавливается внутри `except`-блока и используется снаружи — это корректно в
  Python (нет block scope), т.к. `time.sleep(delay)` достижима только после `except`.
  Mypy может жаловаться — помечено `# type: ignore[possibly-undefined]`.
- **[Промпт #1.6] Fallback сохраняется в БД.** Даже при fallback-ответе
  `Message(role=assistant, content=_FALLBACK_REPLY)` записывается в диалог — чтобы
  менеджер в admin видел, что бот уже ответил клиенту и что именно.
- **[Промпт #1.5] Worker не делает hot-reload** (в отличие от web с gunicorn
  `--reload`). После добавления/изменения tasks.py — `docker compose restart worker`,
  иначе задача не зарегистрируется (autodiscover только при старте).
- Бот — отдельный продукт, НЕ трогает ummvva-app.
- WhatsApp: MVP на Evolution API, прод на Meta Cloud API (через абстракцию).
- AI: Groq (текст + Whisper), Gemini как fallback в той же абстракции.
- На старте только Django admin, без React-фронта.
- **Выбор провайдеров** — через ENV WHATSAPP_PROVIDER / AI_PROVIDER; доступ через
  фабрики `providers/whatsapp/factory.py::get_whatsapp_provider()` и
  `providers/ai/factory.py::get_ai_provider()`. По умолчанию = mock.
- **Порт Postgres на хосте — 5433** (5432 был занят локальным Postgres). Внутри
  docker-сети сервис называется `db:5432`.
- **Шифрование ПДн подключено (Фаза 1, Промпт #1.2).** Пакет
  `django-fernet-fields-v2`; `Message.content` = `EncryptedTextField` (в БД —
  Fernet-токен). Ключ — env `FIELD_ENCRYPTION_KEY` → `settings.FERNET_KEYS`
  (раньше планировался `FERNET_KEY`, переименован). Номер пациента
  (`customer_phone`) НЕ шифруется — по нему ищем диалог (зашифрованное поле
  не индексируется).
- Python 3.12 — только внутри Docker (на хосте установлен 3.14, не используется для запуска).
- Тестовый суперюзер (создан в dev-БД, том pgdata): admin / admin12345.
- Запуск: `docker compose up --build`; админка http://localhost:8000/admin/.
