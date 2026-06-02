# Progress Log — ummvva-bot

## Текущий статус
🟢 Фаза 0 завершена — каркас работает (mock-провайдеры). Готов к Фазе 1.

## Дорожная карта
- [x] Фаза 0 — Каркас: Django + Celery + Postgres + mock-провайдеры + модель Clinic
- [ ] Фаза 1 — Текстовый бот на одну клинику (реальный Groq, webhook, обработка)
- [ ] Фаза 2 — Голосовые сообщения (Whisper через Groq)
- [ ] Фаза 3 — Заявки на запись + уведомление менеджера
- [ ] Фаза 4 — Мультитенант (много клиник на одном сервере)
- [ ] Фаза 5 — Биллинг (месячный тариф)
- [ ] Фаза 6 — Прод (Meta Cloud API, деплой, мониторинг)

## Завершённые промпты
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
Промпт #1 — Фаза 1: осталось — webhook приёма входящих + Celery-задача обработки,
которая склеит «мозг» (build_messages) с провайдерами (generate → send_message).

## Что должно быть сделано (Фаза 1) — план
- [x] Модели переписки + шифрование контента (см. Промпт #1.2). Сделано через
      `Conversation` (несёт `clinic_id`, мультитенант) + `Message` (EncryptedTextField).
      ⚠️ Поле «согласие на обработку ПДн» ещё НЕ добавлено — оно ляжет на
      модель пациента/контакта (отдельный промпт), сейчас сущности Patient нет.
- [x] Реализация GroqAIProvider (см. Промпт #1.1) + регистрация в фабрике.
- [x] «Мозг»: системный промпт из данных клиники + история диалога (см. Промпт #1.3).
      `messaging/services/`: prompt.build_system_prompt, conversation.get_history,
      conversation.build_messages. Проверено на реальном Groq.
- [ ] webhook-эндпоинт приёма входящих (DRF), маршрутизация по номеру-получателю
- [ ] Celery-задача обработки: определить клинику → `build_messages()` →
      AIProvider.generate() → WhatsAppProvider.send_message() → сохранить Message
- [ ] (опц.) EvolutionWhatsAppProvider для приёма/отправки в MVP

## Известные проблемы / решения
- **[FIXED 2026-06-02] GROQ_BASE_URL задвоенный путь → 404.**
  `GROQ_BASE_URL` был `https://api.groq.com/openai/v1`; Groq SDK читает эту переменную
  из окружения и сам добавляет `/openai/v1/chat/completions`, получалось
  `https://api.groq.com/openai/v1/openai/v1/chat/completions`.
  Исправлено: значение укорочено до `https://api.groq.com` в `.env`, `.env.example`
  и дефолте `config/settings.py`. `providers/ai/groq.py` не менялся
  (SDK клиент создаётся без явного `base_url`, значение берётся из ENV).

## Решения и важные детали
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
