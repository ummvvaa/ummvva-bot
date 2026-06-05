"""
Диалог записи: слот-филлинг (Фаза 3, Промпт #3).

Идея: когда пациент хочет записаться, но назвал не всё, бот ВЕЖЛИВО дозапрашивает
недостающее — по ОДНОМУ пункту за раз — не теряя уже собранное. Состояние записи
живёт на `Conversation` (`booking_stage` + `booking_draft`), чтобы между входящими
сообщениями помнить, что уже спросили и что собрали.

СОБИРАЕМ МАКСИМУМ 3 ПОЛЯ: услуга, желаемый день, желаемое время. Имя — по
возможности (не обязательно). Телефон НЕ спрашиваем — он известен из номера
WhatsApp. Это НЕ анкета из 10 вопросов.

ПРАВИЛО ПОДТВЕРЖДЕНИЯ (Фаза 3, см. CLAUDE.md): когда черновик готов, бот НЕ
говорит «вы записаны». Подтверждающую реплику финально соберёт Промпт #4, и она
должна звучать как «передаю заявку администратору», а НЕ как подтверждение приёма.
Бот не подтверждает запись сам — это всегда решение менеджера клиники.

КОНТРАКТ `handle_booking_turn` (по нему действует вызывающий код в #4):
- None  + stage == "none"      → это НЕ про запись, пусть работает обычный флоу Фазы 1.
- str   + stage == "collecting" → уточняющий вопрос: отправить пациенту, заявку НЕ создавать.
- None  + stage == "ready"      → черновик собран: #4 создаёт BookingRequest и шлёт
                                   реплику «передаю заявку администратору».
- str   + stage == "ready"      → анти-тупик: данных не хватает, но пациент не отвечает;
                                   #4 создаёт заявку с тем, что есть, и шлёт ВОЗВРАЩЁННЫЙ
                                   текст («администратор перезвонит и уточнит детали»).
Вызывающий различает случаи по `conversation.booking_stage` после вызова.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time
from datetime import timedelta
from typing import TYPE_CHECKING, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.utils import timezone

from messaging.models import Conversation

from .extraction import extract_booking_intent, parse_when
from .models import BookingRequest

if TYPE_CHECKING:
    from clinics.models import Clinic
    from providers.ai.base import AIProvider

logger = logging.getLogger(__name__)

# --- Валидация желаемого времени записи (Фаза 3) -------------------------------
# Таймзона для проверки «не в прошлом» (клиники в Казахстане).
_VALIDATION_TZ = ZoneInfo("Asia/Almaty")
SLOT_BUFFER_MIN = 60   # запас до закрытия (минимум час)
SLOT_STEP_MIN = 30     # шаг записи (блокирует «8:59»)

# Дни недели → индекс (Monday=0), и латиницей, и кириллическими сокращениями.
# Поддерживаем оба формата working_hours: пример из ТЗ ({"mon": [...], "sun": None})
# и реальный человекочитаемый формат сидов ({"Пн–Пт": "09:00–20:00", "Вс": "выходной"}).
_DAY_INDEX = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
    "пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6,
}
# Символы-разделители диапазона дней/времени: дефис, en-dash, em-dash.
_DASHES = ("–", "—", "-")
# Маркеры выходного дня в значении часов.
_DAYOFF_MARKERS = ("выходн", "closed", "off", "—", "-")


def _split_dash(value: str) -> list[str]:
    """Разбить строку по любому из тире (-, –, —) на куски без пробелов по краям."""
    for dash in _DASHES:
        value = value.replace(dash, "\x00")
    return [part.strip() for part in value.split("\x00") if part.strip()]


def _parse_time(value: str) -> Optional[time]:
    """«09:00» / «9:00» → time; мусор → None."""
    parts = value.strip().split(":")
    if len(parts) != 2:
        return None
    try:
        return time(int(parts[0]), int(parts[1]))
    except (ValueError, TypeError):
        return None


def _day_hours(working_hours: dict, weekday: int) -> Optional[tuple[time, time]]:
    """Часы работы для дня недели (Monday=0) из working_hours любого формата.

    Возвращает (open, close) или None — если в этот день клиника не работает
    либо часы не заданы/не распознаны.
    """
    if not isinstance(working_hours, dict):
        return None

    for raw_key, raw_val in working_hours.items():
        key = str(raw_key).lower().strip()
        endpoints = _split_dash(key)
        # Собираем множество дней, которые покрывает этот ключ.
        days: set[int] = set()
        if len(endpoints) == 2 and endpoints[0] in _DAY_INDEX and endpoints[1] in _DAY_INDEX:
            start, end = _DAY_INDEX[endpoints[0]], _DAY_INDEX[endpoints[1]]
            rng = range(start, end + 1) if start <= end else list(range(start, 7)) + list(range(0, end + 1))
            days.update(rng)
        else:
            for token in endpoints or [key]:
                if token in _DAY_INDEX:
                    days.add(_DAY_INDEX[token])
        if weekday not in days:
            continue

        # День найден — разбираем значение часов.
        if raw_val is None:
            return None
        if isinstance(raw_val, (list, tuple)):
            if len(raw_val) != 2:
                return None
            open_t, close_t = _parse_time(str(raw_val[0])), _parse_time(str(raw_val[1]))
            return (open_t, close_t) if open_t and close_t else None
        text = str(raw_val).lower()
        if any(marker in text for marker in _DAYOFF_MARKERS):
            return None
        bounds = _split_dash(str(raw_val))
        if len(bounds) != 2:
            return None
        open_t, close_t = _parse_time(bounds[0]), _parse_time(bounds[1])
        return (open_t, close_t) if open_t and close_t else None

    return None


def validate_booking(appt_date: date, appt_time: time, working_hours: dict) -> tuple[bool, str]:
    """Проверить желаемые дату/время записи. Возвращает (ok, reason).

    Блокирует: прошлую дату/время; выходной день; время вне часов работы;
    время не кратное 30 минутам; меньше часа до закрытия. reason — готовый
    короткий текст для ответа пациенту (пусто при ok=True).

    working_hours адаптируется под реальную схему Clinic.working_hours (см.
    _day_hours): и формат-пример из ТЗ, и человекочитаемый формат сидов.
    """
    now = datetime.now(_VALIDATION_TZ)
    appt_dt = datetime.combine(appt_date, appt_time, tzinfo=_VALIDATION_TZ)

    if appt_dt <= now:
        return False, "Это время уже прошло, выберите дату и время в будущем."

    hours = _day_hours(working_hours, appt_date.weekday())
    if not hours:
        return False, "В этот день клиника не работает, выберите другой день."

    open_t, close_t = hours
    last_slot = (datetime.combine(appt_date, close_t) - timedelta(minutes=SLOT_BUFFER_MIN)).time()

    if appt_time < open_t or appt_time > last_slot:
        return False, f"Записаться можно с {open_t:%H:%M} до {last_slot:%H:%M} в этот день."

    if appt_time.minute % SLOT_STEP_MIN != 0:
        return False, "Время должно быть кратно 30 минутам, например 10:00 или 10:30."

    return True, ""


def validate_booking_draft(draft: dict, working_hours: dict) -> tuple[bool, str]:
    """Провалидировать распарсенные дату+время из черновика записи.

    Если в черновике нет распознанной даты И времени — проверять нечего, заявку
    пропускаем (частичные данные уточнит администратор) → (True, "").
    """
    raw_date = draft.get("preferred_date")
    raw_time = draft.get("preferred_time")
    if not raw_date or not raw_time:
        return True, ""
    try:
        appt_date = date.fromisoformat(raw_date)
        appt_time = time.fromisoformat(raw_time)
    except (ValueError, TypeError):
        return True, ""
    return validate_booking(appt_date, appt_time, working_hours)


# Сколько раз подряд пациент может НЕ дать нужный слот, прежде чем бот перестанет
# переспрашивать и отдаст заявку менеджеру с тем, что есть (анти-тупик).
_MAX_MISSES = 2

# Сырые слоты, которые сливаем из извлечения в черновик (порядок не важен).
_RAW_SLOT_KEYS = ("service", "preferred_date_raw", "preferred_time_raw", "customer_name")

# Уточняющие вопросы — короткие, вежливые, без давления (тон Clinic, как в Фазе 1).
# Спрашиваем строго по ОДНОМУ недостающему слоту за раз.
_QUESTIONS = {
    "service": "Подскажите, пожалуйста, на какую услугу хотели бы записаться?",
    "date": "На какой день вам было бы удобно прийти?",
    "time": "В какое время вам удобно?",
    "name": "Как вас зовут?",
}

# Реплика анти-тупика: мягко передаём менеджеру, НЕ говорим «вы записаны».
_HANDOFF_REPLY = (
    "Хорошо, давайте я передам заявку администратору — он перезвонит "
    "и уточнит детали. Спасибо за обращение!"
)


def _clinic_today(clinic: "Clinic") -> date:
    """Сегодняшняя дата В ЧАСОВОМ ПОЯСЕ КЛИНИКИ.

    «Завтра»/«сегодня» пациент имеет в виду относительно местного времени клиники
    (клиники в Казахстане, сервер может быть в UTC). Берём таймзону из самой
    клиники; если она задана криво — безопасный фолбэк на серверную дату.
    """
    try:
        return timezone.now().astimezone(ZoneInfo(clinic.timezone)).date()
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning(
            "[booking] неизвестная таймзона %r у клиники %s — берём серверную дату.",
            clinic.timezone,
            clinic.pk,
        )
        return timezone.localdate()


def _first_missing(draft: dict, conversation_name: Optional[str] = None) -> Optional[str]:
    """Первый недостающий слот в порядке: услуга → день → время → имя.

    Слот считается собранным, если пациент что-то сказал по нему (сырая строка
    непустая). Распарсенные date/time best-effort — для них наличие сырой строки
    достаточно (менеджер дочитает raw, если разбор не удался).

    После основных трёх слотов — шаг имени:
    • если имя уже известно из профиля — возвращаем "name_confirm" (подтвердить);
    • если неизвестно — возвращаем "name" (спросить).
    • "_name_pending_confirm" в черновике означает, что подтверждение уже было
      отправлено и обрабатывается в следующем ходе (здесь возвращаем None).
    """
    if not draft.get("service"):
        return "service"
    if not draft.get("preferred_date_raw"):
        return "date"
    if not draft.get("preferred_time_raw"):
        return "time"
    # Имя: собираем после основных слотов.
    if not draft.get("customer_name") and not draft.get("_name_pending_confirm"):
        if conversation_name:
            return "name_confirm"
        return "name"
    return None


def _merge_slots(draft: dict, extracted: dict) -> bool:
    """Слить новые извлечённые слоты в черновик.

    Новое НЕ затирает уже собранное пустыми значениями (только непустое
    обновляет). Возвращает True, если заполнился слот, который раньше был пуст
    (нужно для сброса счётчика анти-тупика).
    """
    filled_new = False
    for key in _RAW_SLOT_KEYS:
        value = extracted.get(key)
        if value:
            if not draft.get(key):
                filled_new = True
            draft[key] = value
    return filled_new


def handle_booking_turn(
    conversation: Conversation,
    incoming_text: str,
    clinic: "Clinic",
    ai: Optional["AIProvider"] = None,
) -> Optional[str]:
    """Один ход диалога записи. Подробный контракт — в докстринге модуля.

    `ai` можно передать явно (для офлайн-тестов на mock); по умолчанию провайдер
    берётся в `extract_booking_intent` через фабрику.
    """
    draft = dict(conversation.booking_draft or {})
    prev_stage = conversation.booking_stage

    # --- Специальный ход: пациент отвечает на вопрос подтверждения имени ---
    # «_name_pending_confirm» в черновике означает, что на прошлом ходе бот спросил
    # «Записываю на имя X, верно?». Обрабатываем ответ (любой ответ считается
    # подтверждением; если в ответе встречается другое имя — обновляем).
    if draft.get("_name_pending_confirm"):
        extracted = extract_booking_intent(incoming_text, clinic, ai=ai)
        new_name = (extracted.get("customer_name") or "").strip()
        if new_name:
            draft["customer_name"] = new_name
        draft.pop("_name_pending_confirm", None)
        draft.pop("_miss_count", None)
        update_fields = ["booking_stage", "booking_draft", "updated_at"]
        # Если пациент назвал другое имя — обновляем и на диалоге.
        if new_name and conversation.customer_name != new_name:
            conversation.customer_name = new_name
            update_fields.append("customer_name")
        conversation.booking_stage = Conversation.BookingStage.READY
        conversation.booking_draft = draft
        conversation.save(update_fields=update_fields)
        return None

    # --- Обычный ход слот-филлинга ---
    extracted = extract_booking_intent(incoming_text, clinic, ai=ai)

    # Не про запись и мы ещё не собираем → это обычный вопрос, пусть его обработает
    # текстовый флоу Фазы 1. Состояние не трогаем.
    if prev_stage == Conversation.BookingStage.NONE and not extracted["wants_booking"]:
        return None

    # Запись активна (явное намерение ИЛИ уже собираем). Дополняем черновик.
    filled_new = _merge_slots(draft, extracted)

    # Best-effort разбор даты/времени из сырых строк (raw храним всегда).
    # «Завтра/сегодня» считаем относительно местного времени КЛИНИКИ.
    date, time = parse_when(
        draft.get("preferred_date_raw"),
        draft.get("preferred_time_raw"),
        today=_clinic_today(clinic),
    )
    draft["preferred_date"] = date.isoformat() if date else None
    draft["preferred_time"] = time.isoformat() if time else None

    known_name = (conversation.customer_name or "").strip() or None
    missing = _first_missing(draft, known_name)

    # Всё собрано → черновик готов, дальше его подхватит #4 (заявка + реплика).
    if missing is None:
        draft.pop("_miss_count", None)
        conversation.booking_stage = Conversation.BookingStage.READY
        conversation.booking_draft = draft
        conversation.save(update_fields=["booking_stage", "booking_draft", "updated_at"])
        return None

    # Чего-то не хватает. Анти-тупик: считаем нерелевантные ответы подряд.
    # Промах = мы УЖЕ собирали (значит спросили), но новый слот так и не пришёл.
    if filled_new:
        misses = 0
    elif prev_stage == Conversation.BookingStage.COLLECTING:
        misses = int(draft.get("_miss_count", 0)) + 1
    else:
        misses = 0  # только начали — это ещё не промах

    if misses >= _MAX_MISSES:
        # Не зацикливаемся: отдаём менеджеру что есть, помечаем готовым.
        logger.info(
            "[booking] анти-тупик: %d промаха подряд, отдаём менеджеру частичную заявку "
            "(clinic %s, conv %s)",
            misses,
            clinic.pk,
            conversation.pk,
        )
        draft.pop("_miss_count", None)
        conversation.booking_stage = Conversation.BookingStage.READY
        conversation.booking_draft = draft
        conversation.save(update_fields=["booking_stage", "booking_draft", "updated_at"])
        return _HANDOFF_REPLY

    # Ещё переспрашиваем — ровно про ОДИН недостающий слот.
    if missing == "name_confirm":
        # Имя известно из профиля: предзаполняем в черновике, ставим флаг ожидания.
        draft["customer_name"] = known_name
        draft["_name_pending_confirm"] = True
        draft.pop("_miss_count", None)
        question: str = f"Записываю на имя {known_name}, верно?"
    else:
        draft["_miss_count"] = misses
        question = _QUESTIONS[missing]

    conversation.booking_stage = Conversation.BookingStage.COLLECTING
    conversation.booking_draft = draft
    conversation.save(update_fields=["booking_stage", "booking_draft", "updated_at"])
    return question


def finalize_booking(conversation: Conversation, clinic: "Clinic") -> BookingRequest:
    """Создать BookingRequest из conversation.booking_draft, сбросить состояние.

    Защита от дублей: если в последние BOOKING_DEDUP_MINUTES уже есть заявка
    от этого диалога со статусом new/notified — обновляем её, не создаём вторую.

    После создания/обновления сбрасывает booking_stage → none и booking_draft → {}.
    """
    draft = conversation.booking_draft or {}

    # --- Дедупликация ---
    dedup_cutoff = timezone.now() - timedelta(minutes=settings.BOOKING_DEDUP_MINUTES)
    existing = (
        BookingRequest.objects.filter(
            conversation=conversation,
            status__in=[BookingRequest.Status.NEW, BookingRequest.Status.NOTIFIED],
            created_at__gte=dedup_cutoff,
        )
        .first()
    )

    # Распарсить сохранённые в черновике ISO-строки → Python-объекты
    preferred_date: Optional[date] = None
    preferred_time_val: Optional[time] = None
    raw_date = draft.get("preferred_date")
    raw_time = draft.get("preferred_time")
    if raw_date:
        try:
            preferred_date = date.fromisoformat(raw_date)
        except (ValueError, TypeError):
            pass
    if raw_time:
        try:
            preferred_time_val = time.fromisoformat(raw_time)
        except (ValueError, TypeError):
            pass

    fields = {
        "customer_phone": conversation.customer_phone,
        "customer_name": draft.get("customer_name") or None,
        "service": draft.get("service", ""),
        "preferred_date_raw": draft.get("preferred_date_raw", ""),
        "preferred_time_raw": draft.get("preferred_time_raw", ""),
        "preferred_date": preferred_date,
        "preferred_time": preferred_time_val,
    }

    if existing:
        for attr, val in fields.items():
            setattr(existing, attr, val)
        existing.save()
        booking = existing
        logger.info(
            "[booking] обновлена существующая заявка #%s (clinic=%s, conv=%s)",
            booking.pk,
            clinic.pk,
            conversation.pk,
        )
    else:
        booking = BookingRequest.objects.create(
            clinic=clinic,
            conversation=conversation,
            **fields,
        )
        logger.info(
            "[booking] создана заявка #%s (clinic=%s, conv=%s)",
            booking.pk,
            clinic.pk,
            conversation.pk,
        )

    # Сброс состояния записи
    conversation.booking_stage = Conversation.BookingStage.NONE
    conversation.booking_draft = {}
    conversation.save(update_fields=["booking_stage", "booking_draft", "updated_at"])

    return booking
