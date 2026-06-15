"""
Детерминированный «судья» слотов записи (Фикс-промпт #1).

Принцип: НИКАКОЙ надежды на LLM в части дат/часов. extraction (Промпт #2) отдаёт
УЖЕ нормализованные значения — `date_iso` (YYYY-MM-DD) и `time_24h` (HH:MM). Этот
модуль их СУДИТ относительно `clinic.hours_by_day`, `clinic.timezone` и переданного
`now`. Только Python, чистые функции, без сети — тестируемо и предсказуемо.

`clinic.hours_by_day` — ЕДИНЫЙ ИСТОЧНИК ПРАВДЫ для часов:
    {"mon": ["09:00","20:00"], ..., "sat": ["10:00","18:00"], "sun": null}
null = выходной.

Каждая причина отказа — короткий КОД (а не текст), чтобы Промпт #2 сам выбрал,
какую фразу показать пациенту:
    past          — дата/время в прошлом
    closed_day    — в этот день клиника не работает (например, воскресенье)
    too_far       — дальше горизонта записи (просим конкретную дату, а не «через год»)
    out_of_hours  — время вне часов работы этого дня
    not_on_grid   — время не на сетке 30 минут (8:59)
    too_late      — меньше часа до закрытия
    unknown_service — услуги нет в прайсе клиники
ok=True → reason=None.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

if TYPE_CHECKING:
    from clinics.models import Clinic

logger = logging.getLogger(__name__)

# Шаг сетки записи (минуты) — блокирует «8:59».
SLOT_STEP_MIN = 30
# Запас до закрытия (минуты) — нельзя записать менее чем за час до конца дня.
SLOT_BUFFER_MIN = 60
# Горизонт записи (дни): дальше — too_far (просим конкретную дату, а не «через год»).
MAX_AHEAD_DAYS = 90

# Фолбэк-таймзона, если у клиники задана криво (клиники в Казахстане).
_FALLBACK_TZ = "Asia/Almaty"
# Индекс дня недели (Monday=0) → ключ в hours_by_day.
_WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _clinic_tz(clinic: "Clinic") -> ZoneInfo:
    """Таймзона клиники (ZoneInfo) с безопасным фолбэком на Asia/Almaty."""
    try:
        return ZoneInfo(clinic.timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        logger.warning(
            "[validation] неизвестная таймзона %r у клиники %s — фолбэк %s",
            getattr(clinic, "timezone", None), getattr(clinic, "pk", "?"), _FALLBACK_TZ,
        )
        return ZoneInfo(_FALLBACK_TZ)


def _parse_hhmm(value) -> Optional[time]:
    """«09:00» → time; мусор/None → None."""
    try:
        return time.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def _day_bounds(clinic: "Clinic", weekday: int) -> Optional[tuple[time, time]]:
    """(open, close) для дня недели (Monday=0) из clinic.hours_by_day.

    None — если день выходной, часы не заданы или заданы некорректно.
    Источник правды строго hours_by_day; в working_hours здесь не заглядываем.
    """
    hours = getattr(clinic, "hours_by_day", None)
    if not isinstance(hours, dict):
        return None
    raw = hours.get(_WEEKDAY_KEYS[weekday])
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        return None
    open_t, close_t = _parse_hhmm(raw[0]), _parse_hhmm(raw[1])
    if open_t is None or close_t is None or open_t >= close_t:
        return None
    return open_t, close_t


def resolve_and_check_date(date_iso: str, *, clinic: "Clinic", now: datetime) -> tuple[bool, Optional[str]]:
    """Судить дату записи (date_iso = YYYY-MM-DD) относительно клиники и `now`.

    Отклоняет: дату в прошлом (past); дальше горизонта записи (too_far); день,
    в который клиника не работает по hours_by_day (closed_day). Иначе (True, None).
    `now` — tz-aware datetime; «сегодня» считаем в таймзоне клиники.
    """
    tz = _clinic_tz(clinic)
    today = now.astimezone(tz).date()

    appt = _parse_date(date_iso)
    if appt is None:
        logger.warning("[validation] кривой date_iso=%r (clinic %s)", date_iso, getattr(clinic, "pk", "?"))
        return False, None

    if appt < today:
        return False, "past"
    if appt > today + timedelta(days=MAX_AHEAD_DAYS):
        return False, "too_far"
    if _day_bounds(clinic, appt.weekday()) is None:
        return False, "closed_day"
    return True, None


def check_time(date_iso: str, time_24h: str, *, clinic: "Clinic", now: datetime) -> tuple[bool, Optional[str]]:
    """Судить время записи (time_24h = HH:MM) для даты date_iso.

    Отклоняет: время не на сетке 30 минут (not_on_grid); вне часов работы дня
    (out_of_hours); меньше часа до закрытия (too_late); время уже прошло, если
    дата = сегодня (past). Иначе (True, None). `now` — tz-aware datetime.
    """
    tz = _clinic_tz(clinic)

    appt_date = _parse_date(date_iso)
    appt_time = _parse_hhmm(time_24h)
    if appt_date is None or appt_time is None:
        logger.warning(
            "[validation] кривой слот date_iso=%r time_24h=%r (clinic %s)",
            date_iso, time_24h, getattr(clinic, "pk", "?"),
        )
        return False, None

    # Сетка 30 минут — проверяем ПЕРВОЙ: «8:59» это not_on_grid, а не out_of_hours.
    if appt_time.minute % SLOT_STEP_MIN != 0:
        return False, "not_on_grid"

    bounds = _day_bounds(clinic, appt_date.weekday())
    if bounds is None:
        return False, "out_of_hours"
    open_t, close_t = bounds

    # Вне окна работы: раньше открытия или в/после закрытия.
    if appt_time < open_t or appt_time >= close_t:
        return False, "out_of_hours"

    # Внутри окна, но меньше часа до закрытия → too_late.
    last_slot = (datetime.combine(appt_date, close_t) - timedelta(minutes=SLOT_BUFFER_MIN)).time()
    if appt_time > last_slot:
        return False, "too_late"

    # Сегодняшнее время уже прошло.
    appt_dt = datetime.combine(appt_date, appt_time, tzinfo=tz)
    if appt_dt <= now.astimezone(tz):
        return False, "past"

    return True, None


def check_service(service_text: str, *, clinic: "Clinic") -> Optional[str]:
    """Сопоставить услугу из сообщения с прайсом клиники (services_json).

    Нормализуем регистр/пробелы, сравниваем по вхождению (в обе стороны).
    Возвращает НАЗВАНИЕ услуги из прайса при совпадении, иначе None («массаж»
    в стоматологии → None).
    """
    query = _normalize(service_text)
    if not query:
        return None
    for item in (getattr(clinic, "services_json", None) or []):
        if isinstance(item, dict):
            name = item.get("name") or item.get("title") or item.get("service")
        else:
            name = item
        if not name:
            continue
        norm_name = _normalize(name)
        if norm_name and (query in norm_name or norm_name in query):
            return name
    return None


def _parse_date(date_iso) -> Optional[date]:
    """«2026-06-10» → date; мусор/None → None."""
    try:
        return date.fromisoformat(str(date_iso))
    except (ValueError, TypeError):
        return None


def _normalize(text) -> str:
    """Нижний регистр + схлопывание пробелов (для сравнения услуг)."""
    if not text:
        return ""
    return " ".join(str(text).lower().split())
