# Progress Log — ummvva-bot

## Текущий статус
🟢 Фаза 1 закрыта — текстовый бот на одну клинику проверен end-to-end с реальными ключами.
🟢 Фаза 2 закрыта — голосовой пайплайн проверен end-to-end на mock.
🟢 Фаза 3 ЗАКРЫТА — заявки на запись + уведомление менеджера:
- Сбор заявки (слот-филлинг): услуга/день/время, анти-тупик, дедуп ✓
- Уведомление менеджера через WhatsApp (mock/Evolution) ✓
- Подтверждение/отказ менеджером: «+N»/«-N» через WhatsApp или руками в admin ✓
- Автоответ пациенту при решении менеджера (confirmed/rejected) ✓
- Admin-actions: «Подтвердить выбранные» / «Отклонить выбранные» с уведомлением пациентов ✓
- seed_booking_demo: демо-заявки в разных статусах для проверки admin ✓
- test_booking_flow: сквозной e2e на mock, 14/14 проверок ✓, чеклист для реального теста ✓
- 38/38 pytest зелёных ✓

🟡 Фаза 4 (мультитенант) — НАЧАТА: уровень ДАННЫХ готов (Промпт #8.1):
- Clinic расширена: `instance_name` (unique), `timezone` (default Asia/Almaty) ✓
- FK `clinic` (on_delete=PROTECT) во всех доменных моделях: Conversation,
  Message (новый прямой FK), BookingRequest ✓
- Data-миграции с бэкфиллом: Message.clinic из conversation.clinic;
  instance_name из EVOLUTION_INSTANCE для single-clinic ✓
- Маршрутизация и админка под мультитенант — СЛЕДУЮЩИЕ промпты.

**Статус Evolution-интеграции:** код EvolutionWhatsAppProvider готов;
для реального теста нужно заполнить .env: EVOLUTION_API_URL, EVOLUTION_API_KEY,
EVOLUTION_INSTANCE (см. CLAUDE.md, раздел «Evolution API (WhatsApp для MVP)»).

## Дорожная карта
- [x] Фаза 0 — Каркас: Django + Celery + Postgres + mock-провайдеры + модель Clinic
- [x] Фаза 1 — Текстовый бот на одну клинику (реальный Groq, webhook, обработка)
- [x] Фаза 2 — Голосовые сообщения (Whisper через Groq)
- [x] Фаза 3 — Заявки на запись + уведомление менеджера
- [ ] Фаза 4 — Мультитенант (много клиник на одном сервере)
- [ ] Фаза 5 — Биллинг (месячный тариф)
- [ ] Фаза 6 — Прод (Meta Cloud API, деплой, мониторинг)

## Завершённые промпты
### Промпт #8.1 — Фаза 4: мультитенант на уровне ДАННЫХ (модели + миграции) — ✅ 2026-06-05
- [x] **Изучены существующие модели перед правкой** (не дублировал): `Clinic` уже
      была (name/whatsapp_number(unique)/services_json/working_hours/address/tone/faq/
      is_active/manager_whatsapp/notifications_enabled/created_at/updated_at).
      `Conversation` и `BookingRequest` уже несли FK `clinic` — расширял, не плодил.
- [x] **Clinic расширена двумя полями:**
      • `instance_name` — CharField(max_length=255, **unique**, null/blank) — имя
        инстанса Evolution / идентификатор подключения. nullable, чтобы старые
        клиники пережили миграцию (бэкфилл из env). Уникален: два подключения на
        одну клинику нельзя.
      • `timezone` — CharField(default="Asia/Almaty") — для корректного разбора
        «завтра/сегодня» относительно местного времени.
      • `services_prices` из ТЗ покрыт уже существующим `services_json` — НЕ
        переименовывал (сломало бы prompt.py/seed/admin).
- [x] **FK `clinic` (on_delete=PROTECT) во всех доменных моделях:**
      • `Conversation.clinic`: CASCADE → **PROTECT** (был, поменял on_delete).
      • `BookingRequest.clinic`: CASCADE → **PROTECT** (был, поменял on_delete).
      • `Message.clinic`: **новый прямой FK** (PROTECT, db_index) — денормализация
        поверх conversation.clinic для прямой изоляции/индексации горячей таблицы
        сообщений без JOIN. PROTECT защищает ПДн от случайного каскадного сноса
        клиники.
- [x] **Уникальность / индексы:** `instance_name` unique; `whatsapp_number` уже
      unique; FK `Message.clinic` и `Conversation.clinic` индексированы (FK → индекс).
- [x] **Миграции с бэкфиллом (data-миграции, не вручную):**
      • `clinics/0003` — schema: instance_name + timezone.
      • `clinics/0004` — data: instance_name ← EVOLUTION_INSTANCE из env ТОЛЬКО для
        однозначного single-clinic случая (1 клиника, env непустой, имя свободно);
        иначе no-op (нельзя вешать один инстанс на несколько клиник).
      • `messaging/0004` — AlterField Conversation.clinic→PROTECT; AddField
        Message.clinic(null=True) → RunPython бэкфилл (clinic ← conversation.clinic
        по диалогам, без N сейвов) → AlterField Message.clinic(NOT NULL). Так
        существующие сообщения на проде не падают на NOT NULL.
      • `bookings/0002` — AlterField BookingRequest.clinic→PROTECT.
- [x] **Код подстроен под NOT NULL Message.clinic:** оба `Message.objects.create`
      в `messaging/tasks.py` (user + assistant) получают `clinic=clinic`; так же в
      `test_brain.py`. `seed_demo_clinic --force` теперь сносит bookings+conversations
      до `clinic.delete()` (иначе ProtectedError на PROTECT).
- [x] **Зелёное:** `makemigrations --check` → No changes detected; `manage.py check`
      → 0 issues; `migrate` применил 4 миграции чисто; **pytest 44/44**.
      Бэкфилл проверен в БД: 64 сообщения, 0 без clinic; timezone у всех Asia/Almaty.

### Промпт #7 — Фаза 3: финализация (admin-actions, seed, E2E test_booking_flow) — ✅ 2026-06-04
- [x] **BookingRequestAdmin** доведён до рабочего инструмента менеджера:
      • `action_confirm_selected` / `action_reject_selected` — bulk-actions вызывают
        `apply_manager_decision` для каждой выбранной заявки (only new/notified),
        пациент получает уведомление; уже закрытые пропускаются с сообщением «N пропущено».
      • `list_display` + `preferred_date_display` (дата + время как сказал пациент),
        `date_hierarchy`, кликабельные ссылки `list_display_links`.
      • `manager_note` — редактируемый в детальном виде (единственное изменяемое поле
        помимо `status`); телефон/имя — readonly-расшифровка.
- [x] **`seed_booking_demo`** (management-команда) — находит «Жемчуг Дент» (77001112233),
      выставляет `manager_whatsapp=77089998877`, создаёт 4 демо-заявки в статусах
      new / notified / confirmed / rejected. Флаг `--force` пересоздаёт.
- [x] **`test_booking_flow`** (management-команда) — сквозной E2E на mock, офлайн:
      • Шаг 1: пациент «хочу записаться на чистку завтра в 3» → mock-AI извлекает все слоты
        → создаётся 1 заявка (new→notified) → менеджер получает «🦷 Новая заявка #N»
        → пациент получает «Передал заявку администратору» (НЕ «вы записаны»).
      • Шаг 2: менеджер «+N» → статус notified→confirmed → пациент получает «✅ подтверждена»
        (НЕ «вы записаны»); менеджер получает «Готово: заявка #N подтверждена».
      • 14/14 проверок зелёных; печатает чеклист ручного теста на реальном Evolution API.
- [x] **pytest 38/38** зелёных, `check` — 0 issues.

### Промпт #6 — Фаза 3: замыкание цикла (решение менеджера → уведомление пациента) — ✅ 2026-06-04
- [x] **Маршрутизация менеджера (КРИТИЧНО):** в `messaging/tasks.py::handle_incoming_message`
      добавлен шаг 0a — ДО любой пациентской обработки (голос/диалог/запись) проверяем,
      не является ли отправитель (`customer_phone`) менеджером какой-то клиники
      (`Clinic.manager_whatsapp == customer_phone`, `is_active=True`). Если да →
      ведём по ветке менеджера и `return` (новую переписку/заявку НЕ заводим).
- [x] **Ветка менеджера** — новый модуль `bookings/manager.py`:
      • `parse_manager_command(text) -> (decision, booking_id, note)|None` — regex:
        «+{id}» / «подтверждаю {id}» → confirm; «-{id}» / «отклоняю {id}» → reject;
        текст после номера → `note` (напр. «+12 приходите к 16:00» → note=«приходите к 16:00»).
      • `apply_manager_decision(booking, decision, note=None)` — общая функция:
        confirm→status=confirmed, reject→status=rejected, сохраняет `manager_note`
        (только если note непустой), триггерит `notify_customer.delay(booking.id)`.
      • `handle_manager_message(clinic, text) -> str|None` — проверка принадлежности:
        `booking.clinic_id != clinic.id` → игнор + лог (None, ничего не шлём, не даём
        менеджеру трогать чужие заявки). Неизвестная команда → подсказка по формату.
        Несуществующая заявка → «Заявка #N не найдена».
- [x] **Celery-задача `notify_customer(booking_id)`** в `bookings/tasks.py`:
      confirmed → «✅ Ваша заявка в «{clinic}» подтверждена: {услуга}, {день} {время}.
      {manager_note}. Ждём вас!»; rejected → «По заявке в «{clinic}» администратор
      предложил уточнить время: {manager_note или 'свяжется с вами'}.» (мягко, без
      негатива). Иной статус → ничего не шлём. Ретрай на `requests.RequestException`
      (exponential backoff, макс. 3), как у `notify_manager`.
- [x] **Путь (Б) — admin:** `BookingRequestAdmin.save_model` шлёт `notify_customer`
      ровно один раз при смене статуса на confirmed/rejected (`"status" in
      form.changed_data and obj.status in {confirmed, rejected}`). Без двойной отправки:
      admin и WhatsApp — разные точки входа, не пересекаются (admin сюда, WhatsApp —
      через `apply_manager_decision`).
- [x] **Фазы 1–2 не сломаны:** обычные пациентские сообщения (текст/голос/вопросы/
      запись) работают как раньше; меняется только то, что сообщения от
      `manager_whatsapp` уходят в ветку менеджера.
- [x] **Тесты** — `bookings/test_manager.py`, 7 шт. (MockProvider, офлайн):
      «+{id}» → confirmed, пациенту одно подтверждение, новая переписка/заявка не
      создана; «+{id} note» → note сохранён и попал пациенту; «-{id}» → rejected +
      мягкий отказ; менеджер чужой клиники → игнор, статус не меняется; неизвестная
      команда → подсказка; admin-смена статуса → `notify_customer` вызван один раз
      (правка только заметки → не вызван); обычное пациентское сообщение → пациентский
      флоу. Полный прогон — **38/38 зелёных**, `check` — 0 issues. Worker перезапущен
      (`notify_customer` зарегистрирована).

### Промпт #5 — Фаза 3: Celery-задача notify_manager (уведомление менеджера) — ✅ 2026-06-04
- [x] `bookings/tasks.py::notify_manager(booking_id)` — `@shared_task(bind=True, max_retries=3)`:
      • грузит `BookingRequest.select_related("clinic")`;
      • если `clinic.notifications_enabled == False` или `manager_whatsapp` пуст →
        логирует «уведомления выключены / нет номера менеджера» и выходит (status="new");
      • формирует сообщение: «🦷 Новая заявка #{id} — {clinic.name}\nУслуга: {service}\n
        Желаемо: {preferred_date_raw} {preferred_time_raw}\nПациент: {name}, {phone}\n
        Ответьте: "+{id}" чтобы подтвердить или "-{id}" чтобы отклонить.»;
      • отправляет через `get_whatsapp_provider()` на `clinic.manager_whatsapp`;
      • при успехе → `status="notified"`, save;
      • на `requests.RequestException` → `self.retry(countdown=2**retries)`, макс. 3 попытки;
        при `MaxRetriesExceededError` — логирует ошибку, status остаётся "new";
      • на прочие исключения — логирует, не роняет задачу.
- [x] `messaging/tasks.py` — удалена синхронная `_notify_manager`; оба вызова
      заменены на `notify_manager.delay(booking.id)`. Добавлен импорт из `bookings.tasks`.
- [x] **Тесты** — `bookings/test_notify.py`, 3 шт. (MockProvider, офлайн):
      • заявка с `manager_whatsapp` → провайдер получил один вызов с `#id` и услугой,
        status → "notified";
      • `notifications_enabled=False` → send не вызывается, status="new";
      • `manager_whatsapp=None` → send не вызывается, без падения.
      Полный прогон — **31/31 зелёных**, `check` — 0 issues.

### Промпт #4 — Фаза 3: создание заявки из черновика + встройка в Celery-флоу — ✅ 2026-06-04
- [x] `config/settings.py` — добавлен `BOOKING_DEDUP_MINUTES` (env, дефолт 30).
- [x] `bookings/flow.py::finalize_booking(conversation, clinic) -> BookingRequest`:
      • Собирает `BookingRequest` из `conversation.booking_draft`: `customer_phone`
        (из диалога), `service`, `preferred_date_raw/time_raw`, `preferred_date/time`
        (из isoformat-строк в черновике), `customer_name`; `status="new"`.
      • Дедупликация: если в последние `BOOKING_DEDUP_MINUTES` уже есть заявка
        от этого диалога со статусом `new`/`notified` — обновляет её (не создаёт дубль).
      • После создания/обновления сбрасывает `booking_stage → none`, `booking_draft → {}`.
- [x] `messaging/tasks.py` — booking-флоу встроен в `handle_incoming_message` между
      шагом «сохранить входящее сообщение» и шагом «AI-генерация»:
      • `str + stage=collecting` → уточняющий вопрос, AI-флоу НЕ вызывается;
      • `str + stage=ready` → анти-тупик: `finalize_booking()` + уведомить менеджера
        + отправить возвращённый текст;
      • `None + stage=ready` → `finalize_booking()` + уведомить менеджера + реплика
        «Спасибо! Передал заявку администратору клиники…» (НЕ «вы записаны»);
      • `None + stage=none` → штатный AI-флоу Фазы 1 (без изменений).
- [x] `_notify_manager(booking, clinic)` в tasks.py: отправляет менеджеру
      `Clinic.manager_whatsapp` уведомление через абстракцию `WhatsAppProvider`
      (если `notifications_enabled`), ставит `booking.status = notified`. Ошибка
      уведомления логируется, задача не падает.
- [x] Голосовой и текстовый флоу Фаз 1–2 не сломаны (запись — надстройка поверх).
- [x] **Тесты** — `bookings/test_finalize.py`, 3 шт. (MockProvider, офлайн):
      • готовый черновик → `finalize_booking` создаёт ровно одну `BookingRequest`,
        все слоты записаны (в т.ч. ПДн через шифрование), stage сброшен, draft пуст;
      • повторный `finalize` в окне дедупа → вторая заявка НЕ создаётся, первая
        обновляется новыми данными;
      • вопрос о цене → `BookingRequest` не создаётся, ответ AI сохранён в БД.
      Полный прогон — **28/28 зелёных**, `check` — 0 issues.

### Промпт #13.2.5 — Фаза 3: диалог записи (слот-филлинг) — ✅ 2026-06-04
- [x] `Conversation` получил состояние записи: `booking_stage` (CharField choices
      `none`/`collecting`/`ready`, default `none`) и `booking_draft` (JSONField,
      default=dict). Миграция `messaging/0002_*`, `migrate` + `check` чисто.
- [x] `bookings/flow.py::handle_booking_turn(conversation, incoming_text, clinic,
      ai=None) -> str|None` — слот-филлинг:
      • вызывает `extract_booking_intent` на входящем;
      • если `stage=none` и `wants_booking=false` → `None` (не запись, обычный
        флоу Фазы 1, состояние не трогаем);
      • иначе сливает новые слоты в `booking_draft` (новое НЕ затирает собранное
        пустым), парсит дату/время best-effort (`parse_when`, raw храним всегда);
      • первый недостающий слот в порядке услуга → день → время → вежливый вопрос
        ровно про ОДИН пункт, `stage=collecting`;
      • всё собрано → `stage=ready`, `None` (сигнал #4 создать заявку).
- [x] Собираем МАКСИМУМ 3 поля (услуга/день/время), имя опционально, телефон не
      спрашиваем (известен из номера WhatsApp). Не анкета.
- [x] Анти-тупик: 2 нерелевантных ответа подряд (`_MAX_MISSES=2`, счётчик
      `_miss_count` в draft) → `stage=ready` с тем, что есть, и реплика «передам
      администратору, перезвонит и уточнит детали». Без бесконечного переспроса.
      Промах считается только если уже `collecting` (значит спрашивали) и новый
      слот не пришёл; старт записи промахом не считается.
- [x] ПРАВИЛО подтверждения зафиксировано в докстринге `flow.py`: при готовом
      черновике бот НЕ говорит «вы записаны»; реплику соберёт #4 как «передаю
      заявку администратору». Контракт возврата (None/str × stage) описан там же.
- [x] `MockAIProvider.generate(json_mode=True)` расширен: помимо `wants_booking`
      по маркерам теперь грубо извлекает услугу (по основам слов из прайса), день
      (по маркерам) и время (по числу часов) — чтобы офлайн прогнать весь слот-флоу.
- [x] **Тесты** — `bookings/test_flow.py`, 4 шт. (MockProvider, офлайн): полный
      сбор «хочу записаться»→услуга→день→время→ready; вопрос о цене → None;
      частичная «запишите на чистку завтра» → спрашивает только время; анти-тупик
      (2 промаха → ready + handoff с частичными данными). Полный прогон — 25/25
      зелёных, `check` — 0 issues.

### Промпт #13.2 — Фаза 3: распознавание намерения записи + парсинг слотов — ✅ 2026-06-04
- [x] `json_mode` проброшен через абстракцию AI: `AIProvider.generate(messages, clinic,
      json_mode=False)` (base) + реализации `mock` и `groq`. В Groq при `json_mode=True`
      добавляется `response_format={"type":"json_object"}` (слово «json» в промпте
      извлечения присутствует — Groq этого требует). Старые вызовы `generate(messages,
      clinic)` не сломаны (дефолт `json_mode=False`).
- [x] `MockAIProvider.generate` в `json_mode` отдаёт детерминированный валидный JSON;
      намерение определяет по маркерам (`запиш`, `жазыл`, `прийти`...) — для офлайн-тестов.
      Вопрос о цене маркеров не содержит → `wants_booking=false`.
- [x] `bookings/extraction.py`:
      • `extract_booking_intent(text, clinic, ai=None) -> dict` — системный промпт
        извлечения собирается из услуг клиники (переиспользует `_format_services` из
        Фазы 1), модель просят вернуть СТРОГО JSON (`json_mode=True`). Результат —
        всегда dict с ключами `wants_booking|service|preferred_date_raw|
        preferred_time_raw|customer_name`. Кривой JSON / исключение провайдера →
        логируем + безопасный fallback (`wants_booking=False`), наружу исключение НЕ
        пробрасываем (флоу не падает). `ai` инъектируется для тестов, по умолчанию —
        фабрика.
      • `parse_when(date_raw, time_raw, today=None) -> (date|None, time|None)` —
        best-effort: «завтра»/«ертен» → +1, «сегодня»/«бугин» → today,
        «послезавтра»/«арги кун» → +2, дни недели (рус + каз русскими буквами) →
        ближайшая будущая дата; время: HH:MM, «сагат 3»/«в 15»/«3-ке», числительные
        словами («к трём»). Не распарсил уверенно → None (raw хранит BookingRequest).
        НЕ выдумываем дату.
- [x] **Тесты (pytest, MockProvider, офлайн)** — `bookings/test_extraction.py`, 16 шт.,
      все зелёные: dict с нужными ключами + булев `wants_booking`; намерение (рус/каз)
      vs вопрос о цене; кривой JSON и исключение провайдера → fallback без падения;
      `parse_when` для «завтра»/«ертен»/«сегодня»/дня недели (рус+каз)/«15:00»/«3-ке»/
      «к трём» и мусора (None, None). Полный прогон — 21/21 зелёных, `check` — 0 issues.

### Промпт #13.1 — Фаза 3 (старт): приложение bookings + модель BookingRequest — ✅ 2026-06-04
- [x] Создано Django-приложение `bookings` (зарегистрировано в `INSTALLED_APPS`).
- [x] Модель `bookings.BookingRequest`:
      • `clinic` FK→Clinic (CASCADE, related_name="bookings", indexed) — мультитенант.
      • `conversation` FK→messaging.Conversation (SET_NULL, null=True) — заявку не
        теряем, даже если переписку удалят (запрос на удаление ПДн).
      • `customer_phone` = `EncryptedCharField` (ПДн, шифротекст в БД).
      • `customer_name` = `EncryptedCharField`, null=True (пациент может не назваться).
      • `service` / `preferred_date_raw` / `preferred_time_raw` — CharField (НЕ ПДн,
        не шифруем — удобно фильтровать в admin).
      • `preferred_date` (DateField) / `preferred_time` (TimeField), null=True —
        распарсенные значения, если разбор удался.
      • `status` choices: new / notified / confirmed / rejected / cancelled,
        default="new", indexed.
      • `manager_note` (TextField, null=True), `created_at` / `updated_at`.
- [x] В `Clinic` добавлены поля уведомления менеджера: `manager_whatsapp`
      (CharField, null=True) и `notifications_enabled` (BooleanField, default=True).
      Выведены в admin (фишсет «Уведомления о заявках»).
- [x] `bookings.admin.BookingRequestAdmin`:
      • list_display: clinic, service, preferred_date_raw, preferred_time_raw, status, created_at.
      • list_filter: clinic, status, created_at.
      • ПДн (телефон/имя) — readonly, видны только в детальном просмотре (в списке нет).
      • Менеджер правит только `status` и `manager_note`; `has_add_permission=False`
        (заявки создаёт бот, не человек руками).
- [x] Миграции: `clinics.0002_*` (поля менеджера) + `bookings.0001_initial`.
      `migrate` прошёл чисто, `manage.py check` — 0 issues.
- [x] **Тесты (pytest, на mock, без сети)** — `bookings/test_models.py`, 5 шт., все зелёные:
      создание/чтение заявки; default status="new"; nullable имя; миграции чисты
      (`makemigrations --check`); **шифрование**: `customer_phone` в БД лежит
      Fernet-токеном (`gAAAA...`, открытого номера нет — проверка сырым SQL-курсором),
      через ORM читается в открытом виде.
- [x] Добавлены `pytest==8.3.4` + `pytest-django==4.9.0` в requirements.txt и
      `pytest.ini` (`DJANGO_SETTINGS_MODULE=config.settings`). В работающем
      контейнере доустановлены через pip (на rebuild подтянутся из requirements).
- [x] CLAUDE.md: добавлен раздел «Заявки на запись (Фаза 3)» с ГЛАВНЫМ ПРАВИЛОМ
      (бот не подтверждает запись сам — только собирает и передаёт менеджеру).

### Промпт #12 — End-to-end верификация Фазы 2 + edge-кейсы голосового — ✅ 2026-06-04
- [x] `messaging/management/commands/test_voice.py` — 3 сценария на mock-провайдерах, eager Celery:
      • Тест 1 (нормальный поток): audioMessage → download_voice_media → transcribe → текст →
        build_messages → generate → send. В БД: user(транскрипт) + assistant. Mock отправил ответ. ✓
      • Тест 2 (просроченное медиа): download_voice_media → None → ранний выход (до поиска клиники),
        диалог НЕ создан, клиенту отправлен `_VOICE_FAIL_REPLY`. ✓
      • Тест 3 (короткое/тихое голосовое, pttMessage): transcribe → None → ранний выход,
        диалог НЕ создан, клиенту `_VOICE_FAIL_REPLY`. ✓
- [x] В логах Теста 1 зафиксировано: `[tasks] голосовое распознано ... '[mock-транскрипт]'` —
      транскрипт попадает в лог до передачи в текстовый пайплайн. ✓
- [x] Фаза 2 закрыта; `[x]` в дорожной карте проставлен.
- [x] `manage.py check` — 0 issues (неявно, структура не менялась).

### Промпт #11 — Голосовой пайплайн: ветка audioMessage в Celery-таске — ✅ 2026-06-04
- [x] `providers/whatsapp/base.py` — в интерфейс `WhatsAppProvider` добавлен
      абстрактный `download_voice_media(message_key_id) -> tuple[bytes, str] | None`
      (скачивание голоса идёт через абстракцию, не напрямую).
- [x] `providers/whatsapp/mock.py::MockWhatsAppProvider.download_voice_media` —
      заглушка `(b"mock-audio-bytes", "audio/ogg")` для тестов без интернета.
      (В `EvolutionWhatsAppProvider` метод уже был — Промпт #9.)
- [x] `messaging/webhook_parser.py` — `IncomingMessage` получил поле
      `message_type` (дефолт `"conversation"`). Парсер распознаёт голос
      (`audioMessage`/`pttMessage`): пропускает с пустым `text`, но требует
      `external_id` (= `key.id`, нужен для скачивания). Текстовые без текста —
      по-прежнему `None`. `external_id` уже нёс `key.id`, отдельное поле не плодил.
- [x] `messaging/views.py` — в `handle_incoming_message.delay(...)` пробрасывается
      `message_type`.
- [x] `messaging/tasks.py::handle_incoming_message` — новый параметр
      `message_type="conversation"`. Ветка (шаг 0) для голосовых ДО общего потока:
      `download_voice_media(external_id)` → если `None`, ответить клиенту
      «Не смог разобрать голосовое, повтори текстом, пожалуйста» и выйти;
      `transcribe(audio_bytes, mimetype)` → если пусто, тот же ответ + выход;
      залогировать транскрипт; `text = transcript` и провалиться в ШТАТНЫЙ
      текстовый пайплайн (шаги 1–8 без изменений — логика ответа НЕ скопирована).
      `text` стал необязательным (`""`), чтобы голос приходил без текста.
- [x] Проверено в Docker (mock-провайдеры, eager Celery):
      • текстовый путь `test_webhook` — зелёный (ничего не сломалось);
      • голос: парс audioMessage → download → transcribe → user(транскрипт) +
        assistant + отправка клиенту — OK;
      • голос-фейл: `download_voice_media`→None → клиенту извинение, диалог НЕ
        создан, пайплайн не запущен — OK.
      • `manage.py check` — 0 issues.

### Промпт #10 — transcribe в AIProvider (Whisper через Groq) — ✅ 2026-06-04
- [x] `providers/ai/base.py::AIProvider.transcribe(audio_bytes, mimetype) -> str | None`:
      сигнатура изменена: вместо `language` принимает `mimetype` (MIME-тип аудио),
      возвращает `str | None` вместо `str` (None при ошибке).
- [x] `providers/ai/groq.py::GroqAIProvider.transcribe`:
      • модель `whisper-large-v3`, `language="ru"` (хардкод — лучшее качество для ru).
      • файл передаётся как `("voice.ogg", audio_bytes)` — Groq принимает ogg/opus напрямую.
      • использует уже созданный `self._client` (тот же ключ, что и для текста).
      • при любом исключении: `logger.error` + возвращает `None` (бот не падает).
- [x] `providers/ai/mock.py::MockAIProvider.transcribe`:
      сигнатура обновлена, возвращает `"[mock-транскрипт]"`.
- [x] `ast.parse` всех трёх файлов в Docker — OK.

### Промпт #9 — download_voice_media в EvolutionWhatsAppProvider — ✅ 2026-06-04
- [x] `providers/whatsapp/evolution.py::EvolutionWhatsAppProvider.download_voice_media(message_key_id)`:
      • `POST {EVOLUTION_API_URL}/chat/getBase64FromMediaMessage/{EVOLUTION_INSTANCE}`
        заголовок `apikey`, тело `{"message": {"key": {"id": message_key_id}}, "convertToMp4": false}`.
      • Из ответа берёт `base64`, декодирует в bytes, возвращает `(audio_bytes, mimetype)`.
      • Ошибки (HTTPError — 404/403, пустой base64, ошибка сети, битый JSON) —
        логируются, возвращается `None`. Бот не падает.
      • Импорты `base64` и `Optional` добавлены в модуль.
      • Существующая заглушка `download_media` сохранена (бросает NotImplementedError
        с подсказкой использовать download_voice_media).
- [x] `py_compile` / `ast.parse` в Docker — OK.
- [ ] Ручной тест с реальным Evolution-инстансом — ждёт заполнения ENV.

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
### Промпт #8.2 — Фаза 4: мультитенант — маршрутизация + админка + изоляция

Уровень ДАННЫХ закрыт (Промпт #8.1: модели + миграции + бэкфилл). Осталось:
- Проверить, что маршрутизация по `Clinic.whatsapp_number` (и/или `instance_name`)
  работает корректно при нескольких клиниках в БД (webhook → tasks → правильная
  клиника). Решить, маршрутизировать ли по instance_name, раз он теперь есть.
- Убедиться, что webhook-токены можно задавать per-clinic (или одного глобального
  достаточно для MVP).
- Расширить `seed_demo_clinic` или добавить `seed_second_clinic` для тестирования
  изоляции данных между клиниками (+ заполнить instance_name второй клиники).
- Проверить изоляцию: сообщения клиники A не видны в admin клиники B.
- Изоляция заявок: менеджер клиники A не трогает заявки клиники B (уже реализовано
  в bookings/manager.py, добавить тест с двумя клиниками сразу).

### Промпт #3.8 — Автоимпорт имени из pushName + умная запись ✅ 2026-06-04
- [x] `Conversation.customer_name` (EncryptedCharField, null=True) — новое поле для
      хранения имени пациента из WhatsApp-профиля. Миграция `messaging/0003_*`.
- [x] Парсер вебхука: `IncomingMessage.push_name` берётся из `data.pushName` payload
      Evolution API. Передаётся через `views.py` в `handle_incoming_message.delay`.
- [x] `handle_incoming_message` (tasks.py): после `get_or_create(conversation)` —
      сохраняем `push_name` в `conversation.customer_name`, только если пришло
      непустое и имя ещё не было сохранено ранее (не перезаписываем вручную).
- [x] `build_system_prompt(clinic, customer_name=None)` — новый параметр. Если имя
      известно: блок «ИМЯ ПАЦИЕНТА: X — обращайся по имени, подтверди перед заявкой».
      Если нет: «неизвестно — спроси при записи». `build_messages` в conversation.py
      автоматически берёт имя из `conversation.customer_name`.
- [x] Логика записи (flow.py):
      • `_first_missing` расширен четвёртым слотом после услуга/день/время:
        `"name_confirm"` (если имя известно) или `"name"` (если нет).
      • Известное имя: бот спрашивает «Записываю на имя X, верно?», ставит
        `_name_pending_confirm=True` в черновике, stage=COLLECTING.
      • Следующий ход (ответ пациента): специальная ветка очищает флаг, при
        необходимости обновляет имя (если назвал другое), stage=READY.
      • Неизвестное имя: бот спрашивает «Как вас зовут?» (через `_QUESTIONS["name"]`);
        mock-извлечение обновлено — грубо распознаёт «меня зовут X» / «зовут X».
- [x] `providers/ai/mock.py` — `_extract_slots_mock` расширен: извлекает имя по
      шаблону «меня зовут/зовут/я X»; json_mode теперь включает `customer_name`.
- [x] Тесты — `messaging/test_push_name.py` (6 шт.) + обновлён `test_full_slot_filling_flow`:
      • `test_push_name_saved_on_first_message` — pushName сохраняется на диалоге;
      • `test_push_name_not_overwritten_by_empty` — пустой push_name не затирает имя;
      • `test_booking_confirms_known_name` — известное имя → «Записываю на имя X, верно?»;
      • `test_booking_asks_name_when_unknown` — пустое имя → «Как вас зовут?»;
      • `test_name_confirmation_accepted` — «да» → stage=READY, имя сохранено;
      • `test_name_confirmation_corrected` — «нет, меня зовут Алия» → имя обновлено.
      `test_full_slot_filling_flow` обновлён: после времени — спрашивает имя, после
      «меня зовут Иван» — READY.
- [x] **44/44 pytest зелёных**, `check` — 0 issues.

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
- **[Промпт #6] Сообщения от `manager_whatsapp` идут в ветку менеджера (НЕ как
  пациент).** Проверка отправителя — первым шагом в `handle_incoming_message`, до
  голоса/диалога/записи; новую переписку/заявку для менеджера не заводим. Команды
  `+{id}`/`-{id}` (и «подтверждаю/отклоняю {id}»), текст после номера → `manager_note`.
  Проверка принадлежности заявки клинике менеджера (`booking.clinic_id == clinic.id`),
  иначе игнор + лог. `apply_manager_decision(booking, decision, note)` ставит статус
  и триггерит `notify_customer` (Celery). Admin-смена статуса на confirmed/rejected
  тоже уведомляет пациента — через `save_model` по `form.changed_data`, без дублей
  (admin и WhatsApp — раздельные точки входа).**
- **[Промпт #5] Уведомление менеджера — Celery-задача `notify_manager` через
  WhatsApp-провайдер, status new→notified. Формат ответа менеджера: +{id}/-{id}.
  Ретрай как у Groq: `requests.RequestException` → `self.retry(countdown=2**retries)`,
  макс. 3 попытки. Выделена из `messaging/tasks.py` в `bookings/tasks.py` — уведомление
  менеджера принадлежит доменной логике booking'а, а не HTTP-пайплайну.**
- **[Промпт #4] `finalize_booking` создаёт `BookingRequest` из черновика, дедуп
  окно `BOOKING_DEDUP_MINUTES=30`. Бот отвечает «передал заявку администратору»,
  не «вы записаны». Уведомление менеджера через `WhatsAppProvider` (статус →
  `notified`). Запись встроена перед Groq-флоу в Celery-обработчике: если
  `handle_booking_turn` вернул None и stage=none — штатный AI-флоу без изменений.**
- **[Промпт #13.2.5] Слот-филлинг в `bookings/flow.py`, состояние на
  `Conversation`** (`booking_stage` + `booking_draft`). Собираем максимум
  услуга/день/время, имя опционально, телефон не спрашиваем (известен из номера).
  Анти-тупик: после 2 промахов отдаём менеджеру что есть. Бот не подтверждает
  запись сам — реплика готового черновика (#4) звучит как «передаю заявку
  администратору», НЕ «вы записаны» (зафиксировано в докстринге `flow.py`).
  Mock-провайдер в json_mode теперь извлекает и слоты (не только намерение) —
  для офлайн-прогона всего флоу.
- **[Промпт #13.2] Намерение записи и слоты извлекаются через AIProvider в
  JSON-режиме** (`bookings/extraction.py`). Вопрос о цене != заявка. Дату/время
  парсим best-effort, при сомнении None — менеджер уточняет. `json_mode` проброшен
  в абстракцию `generate()` (дефолт False, старые вызовы целы); Groq получает
  `response_format=json_object`, mock отдаёт детерминированный JSON по маркерам.
  Извлечение безопасно к сбоям: кривой JSON / падение провайдера → fallback
  `wants_booking=False`, исключение наружу не идёт (флоу обработки не падает).
- **[Промпт #13.1] Заявки на запись (Фаза 3).** Заявки в приложении `bookings`,
  модель `BookingRequest`. ПДн пациента (телефон, имя) шифруются как в `Message`
  (`EncryptedCharField`, в БД — Fernet-токен). Бот не подтверждает приём сам —
  только собирает заявку и передаёт менеджеру (`manager_whatsapp` в `Clinic`).
  Услугу/дату/время не шифруем (не ПДн, удобно фильтровать в admin). `conversation`
  через `SET_NULL` — заявку не теряем при удалении переписки. Тесты — pytest
  (`bookings/test_models.py`), на mock без сети.
- **[2026-06-04] Казахский голос: `language="ru"` убран из `transcribe`.**
  В `providers/ai/groq.py::GroqAIProvider.transcribe` параметр `language="ru"`
  удалён из вызова `client.audio.transcriptions.create`. Теперь `whisper-large-v3`
  сам определяет язык (ru/kk) — клиники в Казахстане, пациенты пишут и на русском,
  и на казахском. Хардкод `ru` ломал распознавание казахской речи.
- **[Промпт #11] Голос превращается в текст ДО входа в текстовый пайплайн.**
  Ветка `audioMessage` в `handle_incoming_message` (шаг 0) только скачивает аудио
  (`download_voice_media`) и расшифровывает (`transcribe`), затем кладёт транскрипт
  в `text` и проваливается в ШТАТНЫЙ текстовый поток (шаги 1–8). Логика ответа
  (роутинг клиники, история, generate, send, дедуп, fallback) НЕ дублируется —
  голос переиспользует существующую обработку. Текстовая ветка не менялась.
  `download_voice_media` поднят в интерфейс `WhatsAppProvider` (был только у
  Evolution) — вызов идёт через абстракцию, mock получил заглушку.
  `key.id` голосового берём из `external_id` (он и так нёс `key.id`) — отдельное
  поле `message_key_id` не плодили; в `IncomingMessage` добавлено лишь
  `message_type`. Дедуп голоса работает по тому же `external_id`; минус — ретрай
  вебхука повторно скачает+расшифрует до проверки дедупа (приемлемо для MVP).
- **[Промпт #10] Транскрипция через Groq Whisper.** Метод `transcribe(audio_bytes, mimetype) -> str | None`
  добавлен в интерфейс `AIProvider`. Реализация в `GroqAIProvider`: модель `whisper-large-v3`,
  язык `"ru"` хардкодом (лучшее качество для русского/казахского), файл передаётся как
  `("voice.ogg", audio_bytes)` — ogg/opus Groq принимает без конвертации. Ключ тот же
  (`GROQ_API_KEY`), что и для текстовой генерации. При ошибке — `logger.error` + `None`.
  MockAIProvider возвращает `"[mock-транскрипт]"`.
- **[Промпт #9] Медиа скачиваем через getBase64FromMediaMessage.** Evolution API
  сам расшифровывает WhatsApp-медиа (Signal-крипту) и отдаёт чистый base64.
  Ручную WhatsApp-крипту (libsignal, ключи из message-объекта) не трогаем.
  Новый метод — `download_voice_media(message_key_id)` → `tuple[bytes, str] | None`;
  он живёт рядом с `send_message` в `EvolutionWhatsAppProvider`. Стандартный
  `download_media(media_id)` остался заглушкой — у Evolution нет «чистого»
  media_id, всегда нужен `key.id` из сообщения.
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
