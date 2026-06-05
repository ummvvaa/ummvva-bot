"""
Юнит-тесты валидации желаемого времени записи (Фаза 3, validate_booking).

Проверяем, что бот НЕ передаёт менеджеру заявку на нерабочее/некорректное время:
раньше открытия, не кратно 30 минутам, в выходной, в прошлом — и пропускает
валидное 10:00. working_hours берём в РЕАЛЬНОМ человекочитаемом формате сидов
(кириллические дни, тире, «выходной») — заодно проверяем адаптацию парсера.

Тесты офлайн, без БД и без сети: validate_booking — чистая функция.
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from bookings.flow import validate_booking

TZ = ZoneInfo("Asia/Almaty")

# Реальный формат Clinic.working_hours (как в seed_demo_clinic / seed_multitenant_demo).
WORKING_HOURS = {
    "Пн–Пт": "09:00–20:00",
    "Сб": "10:00–18:00",
    "Вс": "выходной",
}


def _next_weekday(weekday: int) -> date:
    """Ближайшая будущая дата с заданным днём недели (Monday=0), строго > сегодня."""
    today = datetime.now(TZ).date()
    ahead = (weekday - today.weekday()) % 7 or 7
    return today + timedelta(days=ahead)


def test_before_opening_7am_rejected():
    """7:00 — раньше открытия (09:00) → заявка не проходит."""
    ok, reason = validate_booking(_next_weekday(0), time(7, 0), WORKING_HOURS)
    assert ok is False
    assert reason


def test_not_multiple_of_30_rejected():
    """8:59 — не кратно 30 минутам (и раньше открытия) → не проходит."""
    ok, reason = validate_booking(_next_weekday(0), time(8, 59), WORKING_HOURS)
    assert ok is False
    assert reason


def test_within_hours_but_not_multiple_of_30_rejected():
    """10:15 — внутри часов, но не кратно 30 → именно правило шага 30 минут."""
    ok, reason = validate_booking(_next_weekday(0), time(10, 15), WORKING_HOURS)
    assert ok is False
    assert "30" in reason


def test_sunday_day_off_rejected():
    """Воскресенье — выходной → не проходит."""
    ok, reason = validate_booking(_next_weekday(6), time(12, 0), WORKING_HOURS)
    assert ok is False
    assert reason


def test_past_date_rejected():
    """Вчера — дата в прошлом → не проходит."""
    yesterday = datetime.now(TZ).date() - timedelta(days=1)
    ok, reason = validate_booking(yesterday, time(10, 0), WORKING_HOURS)
    assert ok is False
    assert reason


def test_valid_10am_accepted():
    """10:00 в будущий рабочий день (Пн) → валидно."""
    ok, reason = validate_booking(_next_weekday(0), time(10, 0), WORKING_HOURS)
    assert ok is True
    assert reason == ""


def test_too_close_to_closing_rejected():
    """19:30 при закрытии 20:00 — меньше часа до закрытия → не проходит."""
    ok, reason = validate_booking(_next_weekday(0), time(19, 30), WORKING_HOURS)
    assert ok is False
    assert reason


def test_example_format_list_values_accepted():
    """Адаптация под формат-пример из ТЗ: {"mon": ["09:00","20:00"], "sun": None}."""
    hours = {
        "mon": ["09:00", "20:00"], "tue": ["09:00", "20:00"], "wed": ["09:00", "20:00"],
        "thu": ["09:00", "20:00"], "fri": ["09:00", "20:00"],
        "sat": ["10:00", "18:00"], "sun": None,
    }
    ok, _ = validate_booking(_next_weekday(0), time(10, 0), hours)
    assert ok is True
    ok_sun, _ = validate_booking(_next_weekday(6), time(12, 0), hours)
    assert ok_sun is False
