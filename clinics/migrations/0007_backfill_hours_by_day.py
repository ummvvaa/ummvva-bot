# Бэкфилл hours_by_day из существующего working_hours (Фикс-промпт #1).
#
# Цель: дать каждой клинике машиночитаемые часы работы (источник правды для
# валидации записи). Парсим ИЗВЕСТНЫЙ человекочитаемый формат сидов
# ({"Пн–Пт": "09:00–20:00", "Сб": "10:00–18:00", "Вс": "выходной"}), а также
# формат-пример из ТЗ ({"mon": ["09:00","20:00"], "sun": null}).
#
# Что не распарсилось — оставляем null (заполнит владелец вручную в admin) и
# логируем. working_hours НЕ удаляем (остаётся для людей/совместимости).
from __future__ import annotations

import logging

from django.db import migrations

logger = logging.getLogger(__name__)

# Разделители диапазонов дней/времени: дефис, en-dash, em-dash.
_DASHES = ("–", "—", "-")
# Дни недели → индекс (Monday=0): латиницей и кириллическими сокращениями.
_DAY_INDEX = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
    "пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6,
}
# Ключи результата по дням недели (Monday=0).
_WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
# Маркеры выходного дня в значении часов.
_DAYOFF_MARKERS = ("выходн", "closed", "off")
# Сентинел: значение часов распознать не удалось (мусор).
_UNPARSED = object()


def _split_dash(value: str) -> list[str]:
    """Разбить строку по любому из тире (-, –, —) на непустые куски без пробелов."""
    for dash in _DASHES:
        value = value.replace(dash, "\x00")
    return [part.strip() for part in value.split("\x00") if part.strip()]


def _is_hhmm(value: str) -> bool:
    parts = str(value).split(":")
    if len(parts) != 2:
        return False
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except (TypeError, ValueError):
        return False
    return 0 <= hour <= 23 and 0 <= minute <= 59


def _days_from_key(raw_key) -> set[int]:
    """Множество индексов дней недели, которые покрывает ключ working_hours."""
    key = str(raw_key).lower().strip()
    endpoints = _split_dash(key)
    days: set[int] = set()
    if len(endpoints) == 2 and endpoints[0] in _DAY_INDEX and endpoints[1] in _DAY_INDEX:
        start, end = _DAY_INDEX[endpoints[0]], _DAY_INDEX[endpoints[1]]
        rng = range(start, end + 1) if start <= end else list(range(start, 7)) + list(range(0, end + 1))
        days.update(rng)
    else:
        for token in endpoints or [key]:
            if token in _DAY_INDEX:
                days.add(_DAY_INDEX[token])
    return days


def _value_to_hours(raw_val):
    """Значение часов → ["HH:MM","HH:MM"] | None (выходной) | _UNPARSED (мусор)."""
    if raw_val is None:
        return None
    if isinstance(raw_val, (list, tuple)):
        if len(raw_val) == 2 and _is_hhmm(raw_val[0]) and _is_hhmm(raw_val[1]):
            return [str(raw_val[0]).strip(), str(raw_val[1]).strip()]
        return _UNPARSED
    text = str(raw_val).lower()
    if any(marker in text for marker in _DAYOFF_MARKERS):
        return None
    bounds = _split_dash(str(raw_val))
    if len(bounds) == 2 and _is_hhmm(bounds[0]) and _is_hhmm(bounds[1]):
        return [bounds[0], bounds[1]]
    return _UNPARSED


def backfill_hours_by_day(apps, schema_editor):
    Clinic = apps.get_model("clinics", "Clinic")

    for clinic in Clinic.objects.all():
        # Не перетираем уже заполненные (например, вручную в admin) часы.
        if clinic.hours_by_day:
            continue
        working_hours = clinic.working_hours
        if not isinstance(working_hours, dict) or not working_hours:
            continue

        result = {key: None for key in _WEEKDAY_KEYS}
        recognized = False
        unparsed_keys: list[str] = []

        for raw_key, raw_val in working_hours.items():
            days = _days_from_key(raw_key)
            if not days:
                unparsed_keys.append(str(raw_key))
                continue
            value = _value_to_hours(raw_val)
            if value is _UNPARSED:
                unparsed_keys.append(str(raw_key))
                continue
            for day in days:
                result[_WEEKDAY_KEYS[day]] = value
            recognized = True

        if recognized:
            clinic.hours_by_day = result
            clinic.save(update_fields=["hours_by_day"])
            if unparsed_keys:
                logger.warning(
                    "[migration] клиника %s: часы частично бэкфилнуты, не распознаны ключи %s "
                    "(оставлены null — заполнить вручную в admin)",
                    clinic.pk, unparsed_keys,
                )
        else:
            logger.warning(
                "[migration] клиника %s: working_hours=%r не распознан — hours_by_day оставлен "
                "пустым (заполнить вручную в admin)",
                clinic.pk, working_hours,
            )


class Migration(migrations.Migration):

    dependencies = [
        ("clinics", "0006_clinic_hours_by_day_alter_clinic_working_hours"),
    ]

    operations = [
        # Реверс — no-op: обратный бэкфилл затёр бы ручные правки часов в admin.
        migrations.RunPython(backfill_hours_by_day, migrations.RunPython.noop),
    ]
