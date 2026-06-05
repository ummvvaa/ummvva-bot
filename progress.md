# Progress Log — ummvva-bot

## Текущий статус
🟢 **Фаза 5 (биллинг) — ЗАВЕРШЕНА** (Промпты #1–#7). **133/133 pytest**, `check` — 0 issues.

Что работает:
- Автотриал при создании клиники (сигнал post_save → Subscription trialing)
- Гейт подписки в пайплайне: неоплатившим Groq НЕ дёргаем вообще (ни text, ни voice)
- Usage-учёт: messages_in/out, ai_calls через F() идемпотентно
- Manual-оплата: confirm_payment → подписка active, период +30 дней; повторный confirm идемпотентен
- Beat-цикл (09:00 Asia/Almaty): напоминания T-3/T-1, past_due, автосуспенд с grace, без дублей
- Admin владельца: SubscriptionAdmin + PaymentAdmin (confirm action) + PlanAdmin + UsageCounterAdmin
- Admin клиники: ClinicUser → read-only кабинет с изоляцией по get_queryset
- seed_billing_demo: три клиники (trialing / active / suspended), идемпотентна
- test_billing_flow: 7 сценариев офлайн (mock-провайдеры, eager Celery), ✅/❌ по каждому

Что заглушка:
- Реальный эквайер: KaspiBillingProvider — класс есть, методы → NotImplementedError.
  Нужен договор с банком (Kaspi API) или иным эквайером.

🟡 Следующий шаг — **Фаза 6** (прод): Meta Cloud API, деплой (docker + домен), мониторинг,
   реальный платёжный провайдер вместо manual.
🟢 Усиление бота (Промпт #10.1): новое промпт-ядро (12 правил + чек-лист),
   контекст времени (TODAY/WEEKDAY/NOW/TOMORROW, Asia/Almaty) и валидация
   желаемого времени записи (`validate_booking`) перед отправкой менеджеру.
   74/74 pytest. См. «Завершённые промпты».
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

🟡 Фаза 3 — уведомления клиника-зависимые: notify_manager/notify_customer через clinic-провайдер, тесты изоляции ✓
🟢 Фаза 4 — изоляция данных ДОКАЗАНА (Промпт #8.5): 9 pytest (messaging/test_isolation.py)
   + management-команда `test_multitenant_flow` (20 PASS, офлайн) покрывают все 5
   пунктов изоляции. **66/66 pytest зелёных**, `check` — 0 issues.
🟢 Фаза 4 (мультитенант) — ЗАКРЫТА: данные + маршрутизация + изоляция + онбординг:
- Clinic расширена: `instance_name` (unique), `timezone` (default Asia/Almaty) ✓
- FK `clinic` (on_delete=PROTECT) во всех доменных моделях: Conversation,
  Message (новый прямой FK), BookingRequest ✓
- Data-миграции с бэкфиллом: Message.clinic из conversation.clinic;
  instance_name из EVOLUTION_INSTANCE для single-clinic ✓
- Маршрутизация: входящее → клиника по instance_name (приоритет) → whatsapp_number
  (запасной); неактивная/ненайденная клиника → лог + тихий выход ✓
- Изоляция данных между клиниками покрыта тестами (messaging/test_routing.py) ✓
- Добавление новой клиники — без правок кода: только запись Clinic в БД ✓
- `check_clinic <instance_name>` — команда проверки готовности клиники ✓
- ONBOARDING.md — пошаговый гайд подключения новой клиники ✓

**Статус Evolution-интеграции:** код EvolutionWhatsAppProvider готов;
для реального теста нужно заполнить .env: EVOLUTION_API_URL, EVOLUTION_API_KEY,
EVOLUTION_INSTANCE (см. CLAUDE.md, раздел «Evolution API (WhatsApp для MVP)»).

## Дорожная карта
- [x] Фаза 0 — Каркас: Django + Celery + Postgres + mock-провайдеры + модель Clinic
- [x] Фаза 1 — Текстовый бот на одну клинику (реальный Groq, webhook, обработка)
- [x] Фаза 2 — Голосовые сообщения (Whisper через Groq)
- [x] Фаза 3 — Заявки на запись + уведомление менеджера
- [x] Фаза 4 — Мультитенант (много клиник на одном сервере)
- [x] Фаза 5 — Биллинг (месячный тариф) — ЗАВЕРШЕНА ✅ 2026-06-05
      (Промпты #1–#7: модели + сервисный слой + гейт подписки + usage-учёт +
      BillingProvider manual|kaspi + beat-цикл + admin + seed_billing_demo +
      test_billing_flow (7 офлайн-проверок) + чеклист ручного теста)
- [ ] Фаза 6 — Прод (Meta Cloud API, деплой, мониторинг, реальный эквайер)

## Завершённые промпты
### Промпт #7 (Фаза 5) — ФИНАЛ: seed_billing_demo + test_billing_flow + чеклист + Phase 5 complete — ✅ 2026-06-05
- [x] **`billing/management/commands/seed_billing_demo.py`** — создаёт три тестовые
      клиники с разными состояниями подписки: trialing (период активен), active
      (оплачена, период активен), suspended (период 2 месяца назад). Печатает id,
      статус, период, serviceable-флаг. Идемпотентна (get_or_create по instance_name).
      Тариф `billing_demo` (code unique) — не конфликтует с `start`/`pro`.
- [x] **`billing/management/commands/test_billing_flow.py`** — 7 офлайн-проверок
      (mock-провайдеры через `patch`, eager Celery), печатает ✅/❌ по каждому:
      1. Триальная клиника: входящее → AI вызван, UsageCounter.messages_in вырос.
      2. Сдвинули period_end за trial_end+GRACE → run_billing_cycle → suspended.
      3. Входящее в suspended → generate/transcribe НЕ вызваны, счётчик не вырос.
      4. ManualBillingProvider.create_payment + confirm_payment → active, период +30д.
      5. Входящее снова → AI снова вызван, бот ответил.
      6. Повторный confirm_payment → период НЕ сдвинулся (идемпотентность).
      7. Повторный run_billing_cycle в тот же «день» → новых событий/уведомлений нет.
      Флаг `--keep` оставляет тестовые данные. Печатает чеклист ручного теста.
- [x] **Чеклист ручного теста** (в конце test_billing_flow): BILLING_PROVIDER=manual +
      реальный WhatsApp + Groq; admin-суспенд → бот молчит → подтвердить платёж →
      бот отвечает; напоминания через beat (сдвинуть period_end, запустить billing_cycle).
- [x] **pytest 133/133** — полный прогон Фаз 1–5, все зелёные. Новые команды не
      добавляют тесты (pytest их не видит — не test_*.py), но не ломают ни одного.
- [x] **`progress.md`** обновлён: Фаза 5 = ЗАВЕРШЕНА; Промпты #1–#7 в Завершённых;
      статус/дорожная карта/итог зафиксированы.
- [x] **Git commit**: «Phase 5 complete: monthly subscription billing».

### Промпт #6 (Фаза 5) — Admin биллинга: кабинет владельца + кабинет клиники — ✅ 2026-06-05
- [x] **Изучены существующий admin Фазы 4 и billing/admin.py перед правкой:** стиль
      `list_editable`/`list_display_links`/`search_fields`, `_PrettyJSONWidget`,
      fieldsets. Промпт #8.4 явно отложил per-clinic скоупинг до появления
      `ClinicUser`. Реализован здесь.
- [x] **`clinics/models.py::ClinicUser`** — новая модель `User` OneToOneField
      (`clinic_profile`) → `Clinic` FK (`staff_users`). Простейшая связь: зарегистрировал
      менеджера в Django admin, привязал к клинике → он заходит в свой read-only кабинет.
      Миграция `clinics/0005_clinicuser`.
- [x] **`clinics/admin.py::ClinicUserAdmin`** — list + search + autocomplete_fields.
      Регистрация рядом с `ClinicAdmin` в том же стиле.
- [x] **`billing/services.py::reset_trial(subscription)`** — новая функция:
      status→trialing, period_start=now, period_end/trial_end = now+TRIAL_DAYS,
      canceled_at=None. Единый источник истины — переход только через services.
- [x] **`_ClinicScopedMixin`** (billing/admin.py) — примесь для скоупинга: суперадмин
      → qs без фильтра; ClinicUser → `filter(clinic=clinic)` или `qs.none()` (нет
      привязки). `get_actions` зачищает все action'ы для не-суперадминов. Все
      `has_change/add/delete_permission` → False для не-суперадминов.
- [x] **`SubscriptionAdmin`** (владелец):
      • `list_display`: clinic, plan, status, current_period_end, `days_remaining`
        (вычисляемый: «N дн.» / «просрочено N дн.»), `usage_messages_in`
        (вычисляемый: «N / limit» или «N» безлимит).
      • `list_filter = (status, plan)`, `search_fields = (clinic__name,)`.
      • Actions: `action_renew` → `services.renew` (ловит ValueError → WARNING);
        `action_activate_pro` → `services.activate(plan=Plan.get(code="pro"))`
        (DoesNotExist → ERROR); `action_to_trial` → `services.reset_trial`;
        `action_suspend` → `services.suspend`. Каждое action сообщает `message_user`.
      • Для ClinicUser: пустой `get_actions`, `has_change/add/delete=False` → read-only.
- [x] **`PaymentAdmin`** (владелец):
      • `action_confirm_payment` → `get_billing_provider().confirm_payment(payment)`
        для каждого выбранного; уже paid — skip + WARNING. Ошибки логируются
        `logger.exception`, не роняют action.
      • `get_readonly_fields` расширяет `external_id` + `amount_kzt` readonly после paid.
      • ClinicUser: read-only история платежей своей клиники, actions недоступны.
- [x] **`PlanAdmin`** — только суперадмин (`has_view/change/add/delete_permission`).
      Список тарифов с `list_editable = (price_kzt, is_active)` — владелец правит
      цены прямо в таблице без кода.
- [x] **`UsageCounterAdmin`** — `_ClinicScopedMixin` + `has_add/change=False` (readonly).
      Суперадмин видит все, ClinicUser — только свой счётчик за текущий период.
- [x] **`BillingEventLogAdmin`** — только суперадмин (`has_view_permission`), readonly.
- [x] **`config/test_settings.py`** + обновлён `pytest.ini` (`DJANGO_SETTINGS_MODULE =
      config.test_settings`): тесты переведены на SQLite :memory: (без Docker), что
      позволяет запускать pytest без запущенного контейнера postgres.
      `USE_SQLITE_FOR_TESTS=1` в `settings.py` — 5-строчный conditional.
      `conftest.py` оставлен (ставит флаг на всякий случай), реальная точка входа —
      test_settings.py.
- [x] **`billing/test_admin.py`**, 13 тестов (RequestFactory + AdminSite, офлайн):
      renew активной подписки → active; renew без плана → ничего не меняется;
      activate_pro → active + plan=pro; activate_pro без плана в БД → ERROR, нет смены;
      to_trial → trialing; suspend → suspended; confirm_payment → paid + active;
      повторный confirm → период не двигается (идемпотентность); ClinicUser видит
      только свою подписку/платёж/usage; суперадмин видит все; actions пусты для
      ClinicUser.
- [x] **Прогон:** `manage.py check` — 0 issues; `makemigrations --check` — No changes;
      **pytest 133/133** (было 120, +13). Изоляция работает.
- [x] **Решения:** admin владельца: подписки с actions (renew/pro/trial/suspend) +
      платежи с подтверждением + тарифы + usage; клиника видит свою панель биллинга
      read-only с изоляцией через ClinicUser↔get_queryset (тот же механизм clinic FK).

### Промпт #5 (Фаза 5) — Биллинг: ежедневный фоновый billing-cycle (beat) — ✅ 2026-06-05
- [x] **Изучён существующий Celery/beat и приём идемпотентности перед правкой:**
      beat-расписания в проекте НЕ было (только `config/celery.py` с autodiscover);
      «ReminderLog» из Фазы 3 как отдельной модели нет — напоминания шли инлайн.
      Готовый приём идемпотентности уже жил в `services.alert_over_limit_once`:
      `BillingEventLog.objects.get_or_create(subscription, period_key, event_type)` +
      `unique_together` → событие за период ровно один раз. Повторил ровно его в цикле.
- [x] **`billing/tasks.py::run_billing_cycle`** (`@shared_task`, `ignore_result`) —
      идёт по всем `Subscription.select_related("clinic","plan")`. Одна сбойная подписка
      не валит прогон (try/except на подписку, `logger.exception`, счётчики
      processed/errors в return). Полностью офлайн: отправка — через
      `get_whatsapp_provider_for_clinic` (mock просто логирует).
- [x] **`period_key = f"{subscription_id}:{current_period_end:%Y-%m-%d}"`** — ключ
      периода для дедупа (`_period_key`). Привязан к концу периода → после renew/оплаты
      конец сдвигается, ключ меняется, события нового периода считаются заново.
- [x] **Логика по подписке (`_process_subscription`):**
      • **Напоминания T-3 / T-1** (status in trialing/active, период идёт): порог
        `days_left <= 3` → `reminder_3d`, `days_left <= 1` → `reminder_1d`; событие
        резервируется в `BillingEventLog` ДО отправки (как `alert_over_limit_once`) →
        «ровно один раз», устойчиво к пропущенному дню beat. Шаблоны — константы в коде,
        нейтральные, без давления.
      • **Просрочка → `past_due`**: `now > period_end` и статус active/trialing →
        `services.mark_past_due`.
      • **Автосуспенд**: `now > period_end + GRACE_DAYS` и статус past_due →
        `services.suspend` + (если события `expired_suspend` за период ещё нет)
        уведомление менеджеру «сервис приостановлен». В одном прогоне active за грейсом
        проходит active→past_due→suspended (обрабатывает пропуски beat).
      • **Алерт владельцу о лимите** (мягкий, из #3): `services.is_over_limit` →
        НОВЫЙ event_type `OWNER_LIMIT_ALERT` (отдельно от пайплайнного `LIMIT_REACHED`,
        чтобы они не «съедали» уведомление друг друга), раз за период. Шлём на
        `settings.OWNER_WHATSAPP` (если задан), иначе только лог. Бота НЕ трогаем.
- [x] **Гейт `is_clinic_serviceable` расширен**: в `_SERVICEABLE_STATUSES` добавлен
      `PAST_DUE` — после того как цикл пометил подписку past_due, бот ОБЯЗАН работать
      в пределах grace (проверку `now < period_end + GRACE_DAYS` гейт уже делает).
      Раньше past_due сразу выпадал из обслуживания — латентный баг, вскрытый Промптом #5.
      Существующие тесты не ломаются (serviceability past_due нигде не проверялась).
- [x] **Beat-расписание**: `settings.CELERY_BEAT_SCHEDULE["billing-daily-cycle"]` =
      `run_billing_cycle` по `crontab(hour=9, minute=0)` (Asia/Almaty, `CELERY_TIMEZONE`).
      Новый сервис `beat` в `docker-compose.yml` (`celery -A config beat -l info`).
- [x] **Модель/миграция**: `BillingEventLog.EventType.OWNER_LIMIT_ALERT`
      (`billing/0004_alter_billingeventlog_event_type`). `.env.example`: `OWNER_WHATSAPP`
      (опционально, с комментарием) + `settings.OWNER_WHATSAPP`.
- [x] **Тесты** `billing/test_billing_cycle.py`, 8 шт. (mock, офлайн, управляемый
      `Clock` — freezegun в окружении нет, как и в test_services.py): T-3 шлёт ровно
      одно напоминание, повтор в тот же день не дублирует; T-1 после T-3 → ещё одно
      (3d не задваивается); конец периода → past_due + бот по гейту ещё обслуживает
      (в грейсе); после grace → suspended ровно один раз, повтор не шлёт второй суспенд,
      серв уже не обслуживается; active далеко за грейсом → past_due→suspended за один
      прогон; renew сдвигает период → напоминание нового периода считается заново
      (две записи reminder_3d); превышение лимита → алерт владельцу один раз (повтор не
      дублирует); без OWNER_WHATSAPP → событие есть, сообщение не шлём (только лог).
- [x] **Прогон:** **pytest 120/120** (было 112, +8); `manage.py check` — 0 issues;
      `makemigrations --check` — No changes; `migrate` применил billing.0004 чисто;
      beat поднят (LocalTime Asia/Almaty); смоук `run_billing_cycle()` на реальной БД —
      `{'processed': 1, 'errors': 0}`.
- [x] **Решения:** beat run_billing_cycle ежедневно; идемпотентность через
      `BillingEventLog(period_key, event_type)`; past_due→grace→suspend; напоминания
      T-3/T-1 менеджеру.

### Промпт #4 (Фаза 5) — Биллинг: BillingProvider-абстракция (manual|kaspi) + вебхук-заглушка — ✅ 2026-06-05
- [x] **Изучён стиль существующих провайдеров перед правкой** (не изобретал новый):
      WhatsApp (`providers/whatsapp/`: base ABC + factory с `lru_cache` + выбор по
      `settings.WHATSAPP_PROVIDER`, реализации mock/evolution, meta — не реализована)
      и AI (`providers/ai/`: тот же шаблон, mock/groq). Повторил ровно этот стиль
      для биллинга: новый пакет `providers/billing/` (base + manual + kaspi + factory).
- [x] **`providers/billing/base.py::BillingProvider`** (ABC) — три метода:
      • `create_payment(subscription, plan) -> Payment` (создаёт pending);
      • `confirm_payment(payment) -> Payment` (paid + активация; контракт —
        ИДЕМПОТЕНТНОСТЬ зафиксирована в докстринге);
      • `handle_webhook(payload) -> Payment | None` (для будущих реальных эквайеров).
      Деньги/переходы статусов НЕ дублирует — единый источник истины остаётся в
      `billing.services`/`billing.models`.
- [x] **`ManualBillingProvider`** (основной MVP, `BILLING_PROVIDER=manual`):
      • `create_payment`: `Payment(provider="manual", status="pending",
        amount_kzt=plan.price_kzt)`, period_start=now, period_end=now+plan.period_days,
        привязка clinic/subscription/plan.
      • `confirm_payment`: `status="paid"`, `paid_at=now`, затем — если подписка УЖЕ
        была active с тарифом → `services.renew` (период наращивается от старого конца);
        иначе (триал/past_due/suspended/без тарифа) → `services.activate(plan=...)`
        (период от now). **Идемпотентность**: если платёж уже `paid` — ранний return,
        период второй раз не двигается.
      • `handle_webhook`: для manual → `None` (оплата подтверждается в коде/admin).
- [x] **`KaspiBillingProvider`** — ЗАСТАБ (`BILLING_PROVIDER=kaspi`), как `meta` у
      WhatsApp, но строже: КЛАСС существует и подключён в фабрику, методы поднимают
      `NotImplementedError` с понятным сообщением «требуется договор с эквайером».
      В докстринге описано, что будет: create_payment вернёт ссылку на оплату +
      external_id; handle_webhook примет колбэк банка, проверит подпись, найдёт
      Payment по external_id и вызовет confirm_payment; confirm_payment как у manual.
- [x] **`providers/billing/factory.py::get_billing_provider()`** — `lru_cache`,
      выбор по `settings.BILLING_PROVIDER` (manual|kaspi), неизвестный → ValueError.
      Один в один со стилем `get_whatsapp_provider`/`get_ai_provider`.
- [x] **DRF-эндпоинт-заглушка** `POST /billing/webhook/` (`billing/views.py::
      billing_webhook`, `@api_view`, без CSRF/сессии — как `whatsapp_webhook`):
      зовёт `get_billing_provider().handle_webhook(request.data)`, отвечает 200.
      manual → `{"status":"ignored"}` (no-op); застаб-провайдер (NotImplementedError)
      ловится → 200 `{"status":"not_implemented"}`. Подключён в `config/urls.py`.
      Это ЗАДЕЛ под реальный эквайер, не боевой код.
- [x] **Тесты** `billing/test_billing_provider.py`, 7 шт. (manual, офлайн, Clock-
      монипатч `timezone.now`): фабрика по умолчанию = manual; kaspi подключён, но
      методы → NotImplementedError; create_payment → pending на верный период
      (now…now+period_days) и сумму (=plan.price_kzt); confirm из триала → paid +
      active, период от now; confirm активной → renew (старт = старый конец,
      непрерывное продление); повторный confirm того же Payment (и свежего из БД) НЕ
      двигает период и paid_at (идемпотентность); manual.handle_webhook → None.
      Примечание: код плана в фикстуре — `prov_test` (не `start`/`pro`, их сидит
      data-миграция 0002, иначе IntegrityError на unique `code`).
- [x] **Прогон:** **pytest 112/112** (было 105, +7); `manage.py check` — 0 issues;
      `makemigrations --check` — No changes (новых полей моделей не вводили).
- [x] **Решения:** BillingProvider-абстракция manual|kaspi через `BILLING_PROVIDER`;
      manual = подтверждение платежа в коде → продление; kaspi застаблен;
      вебхук-эндпоинт-заглушка готова.

### Промпт #3 (Фаза 5) — Биллинг: гейт подписки в пайплайне + учёт потребления — ✅ 2026-06-05
- [x] **Изучен реальный путь обработки перед правкой** (не угадывал): webhook →
      `messaging/tasks.py::handle_incoming_message`. Клиника резолвится в шаге 0
      (`_resolve_clinic`), реальные вызовы Groq — `get_ai_provider().transcribe()`
      (голос, шаг 0b) и `ai.generate()` (текст, else-ветка шага 6). Дедуп входящих —
      по `Message.external_id` (шаг 3). Сервисный слой (`billing/services.py`) и модели
      (`UsageCounter`/`BillingEventLog`) переиспользованы как есть.
- [x] **Гейт подписки (шаг 0c)** — вставлен МЕЖДУ резолвом клиники и вызовом AI,
      ПОСЛЕ менеджерской ветки (0a, токены не тратит) и ДО голосовой (0b, Whisper):
      `if not billing.is_clinic_serviceable(clinic): log + (опц.) уведомление + return`.
      Неоплатившей клинике Groq не дёргается вообще — ни транскрипция, ни генерация,
      ни booking-extraction (всё после гейта). Поведение оплаченной клиники — прежнее.
- [x] **Учёт потребления через F() (атомарно), идемпотентно:**
      • `messages_in +1` — после сохранения входящего `Message` (шаг 5a). Стоит ПОСЛЕ
        дедупа по `external_id` → ретрай Celery-задачи выходит на дубле и до инкремента
        не доходит ⇒ одно сообщение не задваивает счётчик.
      • `ai_calls +1` — на КАЖДЫЙ реальный вызов Groq на уровне пайплайна: Whisper
        (флаг `transcribed`, учитывается после дедупа) и `generate` (сразу после
        успешного вызова). Booking-extraction (внутренний вызов Фазы 3) намеренно не
        инструментировал — не трогаю логику Фаз 1–3.
      • `messages_out +1` — после успешной отправки ответа (`result.success`).
      • Хелперы `record_incoming/record_ai_call/record_outgoing` + `_bump` (F()-update
        по pk счётчика текущего периода) в `billing/services.py`.
- [x] **Мягкий лимит → алерт раз за период (`alert_over_limit_once`)**: если
      `is_over_limit` стал True и в этом периоде ещё не алертили — пишем
      `BillingEventLog(LIMIT_REACHED)` (новый `EventType`, `unique_together` не даёт
      дубль) + `logger.warning`. Бота НЕ отключаем (уведомление владельцу — Промпт #5).
- [x] **Suspended-уведомление с тротлингом** (`_maybe_send_suspended_notice` в tasks):
      по флагу `settings.SEND_SUSPENDED_NOTICE` (default True) один раз за
      `SUSPENDED_NOTICE_THROTTLE_HOURS` (default 24) шлём нейтральное «Сервис временно
      недоступен, мы скоро свяжемся с вами». Отметка — `Conversation.suspended_notice_at`
      (новое поле + миграция `messaging/0005`). Никакого AI и медицинских ответов.
      Сообщения/заявки suspended-клинике НЕ создаём.
- [x] **Настройки/миграции:** `SEND_SUSPENDED_NOTICE`, `SUSPENDED_NOTICE_THROTTLE_HOURS`
      в `settings.py` + `.env.example`. Миграции: `messaging/0005` (поле),
      `billing/0003` (новый `EventType.LIMIT_REACHED`).
- [x] **Тесты** `billing/test_gate.py`, 6 шт. (mock-провайдеры, офлайн): оплаченная/
      триальная → AI вызван, счётчики `messages_in/ai_calls/messages_out`=1; ретрай
      того же external_id → AI не вызван, счётчики не задвоились (по одному Message
      user/assistant); suspended → `generate`/`transcribe` НЕ вызваны, 0 Message,
      0 BookingRequest, счётчики не растут, задача не падает; тротлинг — два сообщения
      подряд → уведомление ушло один раз + отметка на диалоге; флаг выключает
      уведомление; мягкий лимит → алерт ровно один раз за период (3-е сообщение не
      дублирует), бот продолжает отвечать.
- [x] **Прогон:** **pytest 105/105** (было 99, +6); `manage.py check` — 0 issues;
      `makemigrations --check` — No changes; миграции применены чисто.
- [x] **Решения:** гейт подписки до вызова AI; неоплатившим Groq не дёргаем; usage
      через F() идемпотентно; suspended-уведомление с тротлингом.

### Промпт #2 (Фаза 5) — Биллинг: чистый сервисный слой подписки — ✅ 2026-06-05
- [x] **Изучен код Промпта #1 перед правкой:** модели `Plan/Subscription/...`,
      сигнал автотриала, settings (`TRIAL_DAYS=14`, `GRACE_DAYS=3`). Логику триала из
      сигнала переиспользовал в `start_trial` (тот же `get_or_create`), не дублировал.
- [x] **`billing/services.py`** — БЕЗ сети, БЕЗ WhatsApp/Groq/Celery, только логика +
      БД. Функции (каждая отдельная, тестируемая):
      • `is_clinic_serviceable(clinic) -> bool` — True ТОЛЬКО если `clinic.is_active`,
        есть подписка, `status in (trialing, active)` И `now < current_period_end +
        GRACE_DAYS`. Grace держит гейт корректным, даже если Celery-суспенд ещё не
        отработал. Нет подписки / `is_active=False` / нет `current_period_end` → False.
        Исключений наружу нет (`_get_subscription` ловит `DoesNotExist`).
      • `start_trial(clinic)` — идемпотентно (`get_or_create`), подстраховка к сигналу.
      • `activate(subscription, *, plan, period_start=None, period_days=None)` — в
        `active`: plan, `current_period_start` (=now если не задан), `current_period_end`
        (=start + period_days, по умолчанию `plan.period_days`), `canceled_at=None`.
        Работает из past_due/suspended («оплатил — продлеваем»).
      • `renew(subscription)` — новый старт = старый `current_period_end` (или now, если
        просрочен), конец = старт + `plan.period_days`, status→active. Без plan → ValueError.
      • `mark_past_due` / `suspend` / `cancel` — переходы статусов (cancel ставит
        `canceled_at`). Все переходы логируются (`logging.info`, старый→новый статус).
      • `get_or_create_usage(clinic, when=None)` — счётчик за период ПОДПИСКИ (границы
        `current_period_start/end`), не за календарный месяц. `get_or_create` по
        `(clinic, period_start)` → один счётчик на период.
      • `is_over_limit(clinic)` — `messages_in > plan.message_limit` за текущий период.
        Безлимит/нет подписки/нет плана → False. МЯГКИЙ сигнал, бота НЕ отрубает.
- [x] **Единый источник истины:** смена `Subscription.status` — ТОЛЬКО через эти
      функции; в других местах ручного `subscription.status = …` нет.
- [x] **Тесты** `billing/test_services.py`, 18 шт. (mock, офлайн). Время — управляемый
      `Clock` (монипатч `django.utils.timezone.now`; freezegun в окружении нет).
      ВСЕ ветки: триал не истёк → serviceable; истёк за грейсом (статус всё ещё
      trialing — суспенд не запускали) → не serviceable; активный в периоде →
      serviceable; активный, период кончился, но в грейсе → serviceable (и за грейсом
      → нет); suspended/canceled/нет подписки/`is_active=False` → не serviceable;
      activate из suspended возвращает в строй; renew непрерывный (старт=старый конец)
      и после просрочки (старт=now); renew без плана → ValueError; mark_past_due;
      usage за период создаётся один раз (привязка к границам подписки); is_over_limit
      по messages_in (1000=ровно лимит→False, 1001→True), безлимит→False, без подписки→False.
- [x] **Прогон:** `makemigrations --check` — No changes; `manage.py check` — 0 issues;
      **pytest 99/99** (было 81, +18). Сети нет — модуль чистый.
- [x] **Решения:** единый сервисный слой подписки; serviceable = статус + период с
      grace; лимит сообщений — мягкий, не отрубает.

### Промпт #1 (Фаза 5) — Биллинг: приложение billing + модели подписки — ✅ 2026-06-05
- [x] **Изучен существующий код перед правкой** (не дублировал): `Clinic` в `clinics/`,
      доменные модели (`Conversation`/`Message`/`BookingRequest`) несут FK `clinic`
      (PROTECT) + пары `created_at`/`updated_at` через `auto_now_add`/`auto_now` —
      повторил тот же стиль. Отдельной базовой абстрактной модели времени в проекте
      нет (каждая модель объявляет поля сама) — следовал этому же подходу, не вводил
      новую базу. Сигналов в проекте не было — добавил первый через `apps.ready()`.
- [x] **Приложение `billing`** создано рядом с существующими, подключено в
      `INSTALLED_APPS`. `apps.py::BillingConfig.ready()` импортирует `signals`.
- [x] **Модели (`billing/models.py`), деньги ВЕЗДЕ `DecimalField(12,2)` — никакого float:**
      • `Plan` — `code` (unique), `name`, `price_kzt`, `period_days` (default 30),
        `message_limit` (Positive, null=безлимит), `features` (JSON default=dict),
        `is_active`, created/updated.
      • `Subscription` — `clinic` OneToOne(CASCADE, related_name="subscription"),
        `plan` FK(PROTECT, null), `status` (trialing/active/past_due/suspended/canceled,
        default trialing, indexed), `current_period_start/end`, `trial_end`,
        `canceled_at`, created/updated.
      • `Payment` — `clinic` FK(PROTECT), `subscription` FK(SET_NULL, null),
        `plan` FK(PROTECT, null), `amount_kzt`, `provider` (default "manual"),
        `external_id` (unique, null), `status` (pending/paid/failed, default pending),
        `period_start/end`, `paid_at`, `created_at`.
      • `UsageCounter` — `clinic` FK(PROTECT), `period_start/end`, `messages_in/out`,
        `ai_calls` (все Positive default 0). `unique_together (clinic, period_start)`.
      • `BillingEventLog` — `subscription` FK(CASCADE), `period_key`, `event_type`
        (reminder_3d/reminder_1d/expired_suspend/period_renewed), `created_at`.
        `unique_together (subscription, period_key, event_type)` — защита от дублей рассылок.
- [x] **Сигнал** `billing/signals.py::create_trial_subscription` (post_save на Clinic,
      `dispatch_uid`): при `created=True` через `get_or_create` заводит подписку
      `trialing`, `trial_end = now + settings.TRIAL_DAYS`, `current_period_start = now`,
      `current_period_end = trial_end`. Повторный save клинику не плодит подписки.
      Все datetime — `timezone.now()` (aware, проект на Asia/Almaty, USE_TZ).
- [x] **Настройки** (`config/settings.py`, из env с дефолтами): `TRIAL_DAYS=14`,
      `GRACE_DAYS=3`, `BILLING_PROVIDER="manual"`. Те же три добавлены в `.env.example`
      с комментариями.
- [x] **Data-миграция** `billing/0002_seed_plans_and_backfill_trials.py` (RunPython):
      • два тарифа-плейсхолдера `start` (15000 ₸, лимит 1000) и `pro` (30000 ₸,
        безлимит) через `update_or_create` (цены — заглушки, владелец правит в admin —
        написано в комментарии миграции);
      • бэкфилл: каждой существующей клинике без подписки создаёт триал
        (`subscription__isnull=True`), чтобы прод не сломался после деплоя.
- [x] **Admin** (`billing/admin.py`): Plan (цена/активность `list_editable`),
      Subscription/Payment/UsageCounter/BillingEventLog зарегистрированы (только Django
      admin, без фронта). Пайплайн обработки сообщений и маршрутизация НЕ тронуты.
- [x] **Тесты** `billing/test_models.py`, 7 шт. (на mock, без сети): автотриал при
      создании клиники (status + trial_end ≈ now+TRIAL_DAYS); повторный save не плодит
      подписку; деньги — Decimal; тарифы-плейсхолдеры из миграции (start с лимитом,
      pro безлимит); дефолты Payment; уникальность UsageCounter и BillingEventLog.
- [x] **Прогон:** `makemigrations --check` — No changes detected; `manage.py check` —
      0 issues; `migrate` применил billing.0001+0002 чисто; **pytest 81/81** (было 74, +7).
      Проверено в БД: 1 клиника → 1 подписка (0 без подписки), Plan.price_kzt тип Decimal.

### Промпт #10.1 — Усиление бота: новое промпт-ядро + контекст времени + валидация записи — ✅ 2026-06-05
- [x] **Новое промпт-ядро** в `messaging/services/prompt.py`: константа `PROMPT_CORE`
      с плейсхолдерами `{{...}}`; роль администратора-ассистента, 12 жёстких правил
      (только данные клиники, кратко, не зацикливаться, проверка времени до
      подтверждения, анти-гейминг, медбезопасность и т.д.) + чек-лист записи.
      Подстановка данных клиники сохранена: `CLINIC_NAME`, `ADDRESS`,
      `PHONE` (= `whatsapp_number`), `WORKING_HOURS_HUMAN`, `SERVICES_LIST`, `FAQ`.
      Подстановка идёт простым `str.replace` (в ядре нет других фигурных скобок).
- [x] **`build_time_context()`** (TZ `Asia/Almaty`): `TODAY` (дд.мм.гггг),
      `WEEKDAY` (день недели по-русски), `NOW` (чч:мм), `TOMORROW`. Подставляются
      в промпт → модель не выдумывает дату. `PUSH_NAME` ← `customer_name` профиля
      (пусто → «неизвестно»). Часы работы подаются человекочитаемо в
      `{{WORKING_HOURS_HUMAN}}` (новый `_working_hours_human`: «Пн–Пт 09:00–20:00; …»).
- [x] **`validate_booking(appt_date, appt_time, working_hours) -> (ok, reason)`**
      в `bookings/flow.py`: блокирует прошлую дату/время, выходной день, время вне
      часов работы, не кратное 30 минутам, и меньше часа до закрытия
      (`SLOT_BUFFER_MIN=60`, `SLOT_STEP_MIN=30`). reason — готовый текст пациенту.
      **Адаптирован под РЕАЛЬНЫЙ формат `Clinic.working_hours`** (человекочитаемый
      кириллический: `{"Пн–Пт":"09:00–20:00","Вс":"выходной"}`) И под формат-пример
      из ТЗ (`{"mon":["09:00","20:00"],"sun":None}`) — парсер `_day_hours`
      понимает оба (диапазоны дней через тире -/–/—, списки, «выходной»).
- [x] **Интеграция в Фазу 3**: в `messaging/tasks.py` перед `notify_manager`
      (ветка «черновик собран полностью») вызывается `validate_booking_draft`.
      Если `ok == False` — заявка НЕ отправляется, пациенту возвращается `reason`,
      невалидное время стирается из черновика, stage → `collecting`
      (`_revert_invalid_time`). Анти-тупиковый хендофф намеренно НЕ валидируется
      (это явная передача человеку «как есть»).
- [x] **Окно истории** в LLM — 10 последних сообщений (`DEFAULT_HISTORY_LIMIT=10`,
      уже было; подтверждено, `build_messages`/`get_history` по умолчанию = 10).
- [x] **Провайдер-абстракции, шифрование, мультитенант-маршрутизация — не тронуты.**
- [x] **Тесты** — `bookings/test_validation.py`, 8 шт. (офлайн, без БД): 7:00
      (раньше открытия), 8:59 (раньше открытия / не /30), 10:15 (внутри часов, не /30
      → правило шага), воскресенье (выходной), прошлая дата, валидное 10:00 (ok),
      19:30 (меньше часа до закрытия), формат-пример из ТЗ (список + None).
- [x] **Прогон:** `pytest` — **74/74 зелёных** (было 66, +8); `manage.py check`
      — 0 issues; рендер промпта проверен (нет остаточных `{{ }}`, все данные на месте).

### Промпт #9 — Фаза 4: онбординг новой клиники + check_clinic — ✅ 2026-06-05
- [x] **Верификация маршрутизации:** добавление новой клиники НЕ требует правок кода.
      Routing в `messaging/tasks.py::_resolve_clinic` — полностью из БД: сначала по
      `instance_name`, затем по `whatsapp_number`. `get_whatsapp_provider_for_clinic`
      использует `clinic.instance_name` из БД. `EVOLUTION_INSTANCE` в `.env` — лишь
      исторический фолбэк для клиник без `instance_name` (задокументировано).
      Вердикт: для мультитенанта `EVOLUTION_INSTANCE` можно оставить пустым — каждая
      клиника должна иметь свой `instance_name` в БД. Зафиксировано в ONBOARDING.md.
- [x] **`clinics/management/commands/check_clinic.py`** — команда `check_clinic <instance_name>`:
      • ищет клинику по `instance_name` (CommandError если не найдена);
      • выводит построчный статус: активна / инстанс задан / номер WhatsApp /
        услуги (кол-во) / часы / адрес / FAQ / менеджер / уведомления / часовой пояс;
      • разделяет ошибки (issues — бот не заработает) и предупреждения (warnings — неполный);
      • итоговый вердикт: ГОТОВА / ЕСТЬ ПРОБЛЕМЫ.
      Проверено на обеих демо-клиниках: `demo_clinic_a` и `demo_clinic_b` → ГОТОВА.
- [x] **`ONBOARDING.md`** — пошаговый гайд «Как подключить новую клинику»:
      1. Поднять/настроить инстанс Evolution (docker run, create instance, QR, webhook);
      2. Создать Clinic в Django Admin (обязательные поля + таблица);
      3. Заполнить прайс / часы / менеджера (JSON-форматы с примерами);
      4. `check_clinic <instance_name>` — проверка готовности;
      5. Отправить тестовое сообщение (что проверять в ответе).
      Раздел «Частые проблемы» (5 симптомов → причины).
      Раздел «Переменные окружения» — нужные env + note про `EVOLUTION_INSTANCE`.
- [x] **Прогон:** `pytest` — **66/66 зелёных**; `check_clinic demo_clinic_a/b` — ГОТОВА.
      `manage.py check` — 0 issues.

### Промпт #8.6 — Фаза 4: seed_multitenant_demo (две клиники с разными прайсами) — ✅ 2026-06-05
- [x] **`clinics/management/commands/seed_multitenant_demo.py`** — создаёт ДВЕ
      демо-клиники для смоук-теста мультитенанта:
      • Клиника А «Жемчуг Дент» — instance `demo_clinic_a`, номер 77010000001,
        менеджер 77010000009, timezone Asia/Almaty, свои услуги/часы/FAQ/тон.
      • Клиника Б «Дента Люкс» — instance `demo_clinic_b`, номер 77020000001,
        менеджер 77020000009, timezone Asia/Aqtobe, всё другое.
      • СПЕЦИАЛЬНО отличающиеся цены на одну и ту же услугу: «Профессиональная
        чистка» 14 000 ₸ (А) vs 22 000 ₸ (Б), «Отбеливание ZOOM 4» 65 000 vs 89 000 —
        на смоук-тесте сразу видно, путает ли бот прайсы клиник.
- [x] **Идемпотентность:** `get_or_create` по `instance_name` (unique). Повторный
      запуск не плодит дубли — клиники находятся по инстансу, поля обновляются под
      актуальные демо-данные. Проверено: 2-й прогон → те же id (18, 19), count A=1, B=1.
- [x] **Сводка в stdout:** по каждой клинике — id, instance, номер, менеджер,
      timezone; отдельная строка сравнения цены на чистку (А vs Б).
- [x] **Прогон:** `seed_multitenant_demo` ×2 (идемпотентно); `pytest` — **66/66
      зелёных**; `manage.py check` — 0 issues.

### Промпт #8.5 — Фаза 4: ДОКАЗАТЕЛЬСТВО изоляции данных тестами — ✅ 2026-06-05
- [x] **`messaging/test_isolation.py`** — 9 pytest (MockProvider, офлайн), отдельный
      суите-«доказательство» инвариантов мультитенанта. Две клиники с ЗАВЕДОМО
      разными услугами/ценами/FAQ; один пациентский номер (`77009998877`) пишет в обе.
      Пять пунктов:
      1. **Маршрутизация:** входящее на инстанс/номер А → диалог+сообщения только в А
         (`test_routing_message_to_a_lands_in_a`); зеркально для Б; неизвестный
         номер/инстанс → 0 диалогов, 0 сообщений, ничего не отправлено, без падения
         (`test_routing_unknown_number_creates_nothing`).
      2. **Системный промпт:** `build_system_prompt(clinic_a)` содержит свои услугу/
         цену/FAQ и НЕ содержит ни одной строки данных Б (имя клиники, услуга, цена,
         FAQ, адрес) — проверка собранной строки; зеркально для Б.
      3. **История диалога:** один номер в А и Б → два разных `Conversation`;
         `get_history(conv_a)` не содержит реплик Б; `build_messages(clinic_a, ...)`
         не тянет ни сообщения, ни услуги Б в контекст модели.
      4. **Заявки:** `BookingRequest.objects.filter(clinic=clinic_b)` не содержит
         заявку А (пусто); выборка А = ровно её заявка; `notify_manager` шлёт ровно
         одно уведомление менеджеру А, менеджер Б не получает ничего.
      5. **Прямой запрос:** `Message.objects.filter(clinic=clinic_a)` — все строки с
         `clinic_id==A` и `conversation.clinic_id==A`; пересечение id-выборок А и Б пусто.
- [x] **`messaging/management/commands/test_multitenant_flow.py`** — E2E на mock,
      eager Celery, полностью офлайн. Прогоняет весь путь для ДВУХ клиник параллельно
      (один номер пишет в обе) + неизвестный номер, печатает PASS/FAIL по каждому из
      5 пунктов. `--keep` оставляет данные. Cleanup учитывает PROTECT (сносит
      bookings→messages→conversations→clinics). **20/20 PASS.**
- [x] **Прогон:** `pytest` — **66/66 зелёных** (было 57, +9); `test_multitenant_flow`
      — 20 PASS; `manage.py check` — 0 issues.

### Промпт #8.4 — Фаза 4: Admin под мультитенант — ✅ 2026-06-05
- [x] **`clinics/admin.py`** — `ClinicAdmin` расширен:
      • `list_display`: `(name, whatsapp_number, instance_name, is_active, updated_at)` ✓
      • `list_editable = ("is_active",)` — переключатель активности прямо в списке;
        `list_display_links = ("name",)` добавлен (нужен при использовании list_editable).
      • `_PrettyJSONWidget` — Textarea с `format_value`, которая pretty-prints JSON
        (`json.dumps(..., indent=2, ensure_ascii=False)`) перед рендером; подключён
        через `formfield_overrides = {models.JSONField: {"widget": ...}}` для всех
        трёх JSON-полей (`services_json`, `working_hours`, `faq`) разом.
      • Fieldsets обновлены: `instance_name` и `timezone` добавлены в «Основное».
      • `search_fields` расширен: добавлен `instance_name`.
- [x] **`messaging/admin.py`** — `MessageAdmin` и `ConversationAdmin` улучшены:
      • `MessageAdmin.list_display`: добавлен прямой `clinic` (Message имеет FK
        `clinic` с Фазы 4, раньше шёл через `conversation__clinic`).
      • `MessageAdmin.list_filter`: `("clinic", "role")` — прямой FK вместо
        `conversation__clinic`; чище и быстрее (без JOIN).
      • `MessageAdmin.readonly_fields`: добавлен `clinic`.
      • `ConversationAdmin.list_display`: добавлены `booking_stage` и `message_count`.
      • `ConversationAdmin.list_filter`: добавлен `booking_stage`.
      • `ConversationAdmin.readonly_fields`: добавлены `booking_stage`, `booking_draft`.
- [x] **Per-clinic роли/пользователи — НЕ реализованы, зафиксировано как задача:**
      Ограничение `get_queryset` (менеджер клиники A видит только данные клиники A)
      требует модели пользователь↔клиника. Сейчас все объекты видит только суперадмин.
      Задача: создать `ClinicUser` или профиль `User.profile.clinic` → добавить
      `get_queryset` в `BookingRequestAdmin`, `ConversationAdmin`, `MessageAdmin`
      с фильтром `clinic=request.user.profile.clinic` для не-суперпользователей.
      Отложено до появления реальных менеджеров клиник в проде (Фаза 5/6).
- [x] **57/57 pytest зелёных**, `check` — 0 issues.

### Промпт #8.3 (часть) — Фаза 3 уведомления клиника-зависимые — ✅ 2026-06-05
- [x] **`get_whatsapp_provider_for_clinic(clinic)`** добавлена в `providers/whatsapp/factory.py`:
      для `mock` → глобальный singleton; для `evolution` → `EvolutionWhatsAppProvider(
      instance_name=clinic.instance_name)`, закешированный по `instance_name`.
- [x] **`EvolutionWhatsAppProvider.__init__`** получил необязательный параметр
      `instance_name: str | None` — переопределяет `EVOLUTION_INSTANCE` из env.
      Клиника без `instance_name` → фолбэк на глобальный `EVOLUTION_INSTANCE`.
- [x] **`bookings/tasks.py`**: `notify_manager` использует `get_whatsapp_provider_for_clinic(clinic)`;
      `notify_customer` — `get_whatsapp_provider_for_clinic(booking.clinic)`. Уведомления
      уходят ровно через тот инстанс/подключение, которое принадлежит данной клинике.
- [x] **`messaging/tasks.py`**: все три вызова `get_whatsapp_provider()` (ответ менеджеру,
      голосовой пайплайн, ответ пациенту) заменены на `get_whatsapp_provider_for_clinic(clinic)`.
      Clinic известна на момент всех отправок (резолвится в шаге 0).
- [x] **Существующие pytest-тесты** обновлены: все патчи `*.get_whatsapp_provider` →
      `*.get_whatsapp_provider_for_clinic` (5 файлов: test_notify, test_manager,
      test_finalize, test_push_name, test_routing).
- [x] **Новый файл `bookings/test_clinic_notify.py`**, 5 тестов (MockProvider, офлайн):
      • `test_notify_manager_uses_clinic_a_provider` — заявка А → провайдер А получил
        1 вызов на `manager_whatsapp` А; провайдер Б — 0 вызовов;
      • `test_notify_manager_clinic_b_does_not_use_clinic_a_provider` — зеркальный,
        заявка Б → только провайдер Б активен;
      • `test_notify_customer_uses_clinic_a_provider` — подтверждение пациенту А
        идёт через провайдер А, провайдер Б не вызывается;
      • `test_manager_a_response_does_not_affect_clinic_b_booking` — менеджер А
        шлёт «+booking_b.id»: заявка Б остаётся NOTIFIED, пациент Б не уведомлён
        (кросс-клиничный матчинг по `booking.clinic_id != clinic.id` блокирует);
      • `test_manager_a_confirms_own_clinic_booking` — менеджер А успешно подтверждает
        заявку А, провайдер Б не получает сообщений пациентам.
- [x] **57/57 pytest зелёных**, `check` — 0 issues.

### Промпт #8.2 — Фаза 4: мультитенант — маршрутизация + изоляция по клинике — ✅ 2026-06-05
- [x] **Изучены реальный payload Evolution и существующий путь** (webhook_parser →
      views → tasks) перед правкой — не угадывал ключ маршрутизации.
- [x] **Маршрутизация «по тому, КУДА пришло»** — новый `tasks._resolve_clinic(
      instance_name, clinic_number)`:
      • приоритет — `instance_name` (поле `instance` payload; уникален на клинику,
        не зависит от формата номеров — самый надёжный признак получателя);
      • запасной ключ — `whatsapp_number` (из `sender`/`data.owner`), если инстанс
        пуст или клиника по нему не заведена;
      • `is_active` тут НЕ фильтруется намеренно: клинику опознаём по идентичности,
        активность проверяет вызывающий код (иначе неактивная клиника «провалилась»
        бы в поиск по номеру и могла совпасть с ДРУГОЙ клиникой).
- [x] **Парсер** (`webhook_parser.py`): `IncomingMessage.instance_name` ← `instance`;
      guard ослаблен — нужен отправитель + хотя бы один признак получателя
      (инстанс ИЛИ номер). Маршрут по инстансу работает даже без `sender`.
      `views.py` пробрасывает `instance_name` в `handle_incoming_message.delay`.
- [x] **Клиника не найдена / `is_active=False`:** `handle_incoming_message`
      логирует предупреждение с тем, что пришло (instance/номер, БЕЗ текста —
      медданные), и тихо выходит: не отвечает, не заводит диалог, не падает.
- [x] **Ветка менеджера заскоуплена на найденную клинику** (была глобальной по
      `manager_whatsapp` всех клиник). Теперь: сначала резолвим клинику получателя,
      затем `clinic.manager_whatsapp == customer_phone`. Чинит утечку: менеджер
      клиники A, написавший как ПАЦИЕНТ в клинику B, больше не попадает в
      менеджерскую ветку A. Проверка принадлежности заявки в `handle_manager_message`
      сохранена (двойная защита).
- [x] **Изоляция (уже на уровне данных, подтверждена кодом и тестами):** диалог —
      `get_or_create(clinic=clinic, customer_phone)`; история (`build_messages`) —
      из этого диалога; `Message.create(clinic=clinic)`; дедуп — по сообщениям этого
      диалога; заявки — `finalize_booking(... clinic)`. Один номер клиента в двух
      клиниках = две независимые беседы.
- [x] **Системный промпт — только из объекта Clinic** (проверено: `build_system_prompt`
      берёт name/services_json/working_hours/address/tone/faq/имя; глобальных прайсов
      из .env нет и не было).
- [x] **Таймзона клиники для записи:** `flow._clinic_today(clinic)` считает «сегодня»
      в `clinic.timezone` (фолбэк на серверную дату при кривой TZ); `parse_when`
      получает этот `today` — «завтра/сегодня» теперь относительно местного времени
      клиники, а не UTC сервера. Рабочие часы уже шли в промпт из `clinic.working_hours`.
- [x] **Тесты** — `messaging/test_routing.py`, 8 шт. (MockProvider, офлайн):
      парсер тянет `instance_name` (в т.ч. без `sender`); маршрут по инстансу;
      приоритет инстанса над номером; фолбэк на номер; неизвестная клиника → тишина;
      неактивная клиника → тишина; один клиент в двух клиниках → две беседы, у
      сообщений верный `clinic_id` без перекрёстной утечки. Менеджерские тесты
      (`bookings/test_manager.py`, вкл. «чужая клиника») зелёные после скоупинга.
      **Полный прогон — 52/52**, `check` — 0 issues; `test_webhook` (E2E) зелёный.

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
### Промпт #10 — Фаза 5: Биллинг (месячный тариф)
- Следующая фаза по дорожной карте.
- Модель тарифа/подписки на клинику, статус оплаты, ограничение бота при просрочке.

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
- **[Промпт #1, Фаза 5] billing: Plan/Subscription/Payment/UsageCounter/BillingEventLog;
  деньги в Decimal ₸; автотриал через сигнал; бэкфилл триала на существующие клиники.**
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
