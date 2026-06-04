"""
Распознавание намерения записаться + извлечение слотов заявки (Фаза 3).

Идея: на каждое входящее сообщение мы спрашиваем модель (через абстракцию
`AIProvider`, как в Фазе 1) — хочет ли пациент записаться, и если да, какие
услуга / дата / время / имя он назвал. Ответ требуем СТРОГО в JSON
(`json_mode=True`), без преамбулы и markdown.

ВАЖНО:
- Вопрос о цене («сколько стоит чистка?») — это НЕ заявка (`wants_booking=false`),
  на него отвечает обычный текстовый флоу Фазы 1.
- Дату/время парсим best-effort: если уверенно распарсить нельзя — оставляем None
  (raw-строку сохраняем всегда). НЕ выдумываем дату — лучше None, менеджер уточнит.
- Язык: пациенты пишут на русском И на казахском русскими буквами без диакритики
  («жазылайын», «ертен», «сагат 3-ке») — это уже работало в Фазе 1, не ломаем.

Бот НИЧЕГО не подтверждает — он только собирает заявку и передаёт менеджеру.
"""
from __future__ import annotations

import datetime
import json
import logging
import re
from typing import TYPE_CHECKING, Optional

from messaging.services.prompt import _format_services
from providers.ai.base import AIProvider
from providers.ai.factory import get_ai_provider

if TYPE_CHECKING:
    from clinics.models import Clinic

logger = logging.getLogger(__name__)

# Ключи, которые ВСЕГДА присутствуют в результате extract_booking_intent.
_EMPTY_RESULT = {
    "wants_booking": False,
    "service": None,
    "preferred_date_raw": None,
    "preferred_time_raw": None,
    "customer_name": None,
}


def _build_extraction_prompt(clinic: "Clinic") -> str:
    """Системный промпт для извлечения намерения записи из сообщения.

    Содержит список услуг клиники (как в Фазе 1), чтобы модель сопоставляла
    свободную формулировку («хочу отбелить зубы») с реальной услугой из прайса.
    Слово «json» в промпте обязательно — Groq требует его для json_object-режима.
    """
    services = _format_services(clinic.services_json)
    return f"""\
Ты — модуль извлечения данных для стоматологической клиники «{clinic.name}».
Твоя ЕДИНСТВЕННАЯ задача — проанализировать сообщение пациента и вернуть СТРОГО
один JSON-объект. Без преамбулы, без пояснений, без markdown, без ```.

Формат JSON (ровно эти ключи):
{{
  "wants_booking": true|false,
  "service": "<услуга словами или null>",
  "preferred_date_raw": "<как пациент сказал про день, или null>",
  "preferred_time_raw": "<как пациент сказал про время, или null>",
  "customer_name": "<имя, если представился, иначе null>"
}}

Правила:
- wants_booking = true ТОЛЬКО при ЯВНОМ намерении записаться/прийти на приём
  («хочу записаться», «запишите меня», «можно прийти завтра», по-казахски
  «жазылайын», «жазылғым келеди»).
- ВОПРОС О ЦЕНЕ или информации («сколько стоит чистка?», «канша турады?»,
  «у вас есть рассрочка?») — это НЕ заявка: wants_booking = false.
- service: если узнаёшь услугу в сообщении — верни её словами по прайсу клиники
  ниже (сопоставь «отбелить зубы» с реальной услугой из списка). Если услуга не
  названа или непонятна — null.
- preferred_date_raw / preferred_time_raw: верни ровно как сказал пациент
  («завтра», «ертен», «в субботу», «сагат 3-ке», «после обеда»). Если не сказал — null.
- customer_name: только если пациент явно представился. Иначе null.
- Не выдумывай ничего, чего нет в сообщении. Сомневаешься — ставь null.

Пациент может писать на казахском русскими буквами без спецсимволов
(«жазылайын» = жазылайын, «ертен» = ертең, «канша» = қанша). Понимай это.

УСЛУГИ И ЦЕНЫ КЛИНИКИ (для сопоставления service):
{services}"""


def extract_booking_intent(
    text: str,
    clinic: "Clinic",
    ai: Optional[AIProvider] = None,
) -> dict:
    """Извлечь намерение записаться и слоты заявки из сообщения пациента.

    Возвращает dict с ключами _EMPTY_RESULT. Безопасно к сбоям: если модель
    вернула кривой JSON или провайдер упал — логируем и возвращаем безопасный
    fallback (wants_booking=False), наружу исключение НЕ пробрасываем. Флоу
    обработки сообщения не должен падать из-за извлечения.

    `ai` можно передать явно (для тестов на mock); по умолчанию берём провайдер
    через фабрику (как в остальном коде).
    """
    if ai is None:
        ai = get_ai_provider()

    messages = [
        {"role": "system", "content": _build_extraction_prompt(clinic)},
        {"role": "user", "content": text or ""},
    ]

    try:
        raw = ai.generate(messages, clinic, json_mode=True)
    except Exception as exc:  # провайдер недоступен / сетевой сбой
        logger.error("[extraction] generate failed for clinic %s: %s", clinic.pk, exc)
        return dict(_EMPTY_RESULT)

    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("ожидался JSON-объект")
    except (ValueError, TypeError) as exc:
        # Кривой JSON / не-объект / мусор — не падаем, отдаём безопасный fallback.
        logger.warning(
            "[extraction] не смог распарсить JSON от провайдера (clinic %s): %s; raw=%r",
            clinic.pk,
            exc,
            (raw[:200] if isinstance(raw, str) else raw),
        )
        return dict(_EMPTY_RESULT)

    # Нормализуем: гарантируем все ключи и тип wants_booking = bool.
    result = dict(_EMPTY_RESULT)
    result["wants_booking"] = bool(data.get("wants_booking", False))
    for key in ("service", "preferred_date_raw", "preferred_time_raw", "customer_name"):
        value = data.get(key)
        # Пустые строки/«null» текстом приводим к None.
        if value in (None, "", "null", "None"):
            result[key] = None
        else:
            result[key] = str(value).strip() or None
    return result


# ---------------------------------------------------------------------------
# Best-effort парсинг даты/времени из *_raw.
# ---------------------------------------------------------------------------

# Дни недели (понедельник=0 .. воскресенье=6). Русский + казахский русскими
# буквами; берём по основе слова, чтобы ловить формы («в субботу», «сенбиде»).
_WEEKDAY_STEMS: dict[str, int] = {
    # Понедельник
    "понедельник": 0, "дуйсенби": 0, "дүйсенбі": 0,
    # Вторник
    "вторник": 1, "сейсенби": 1, "сейсенбі": 1,
    # Среда
    "сред": 2, "саросенби": 2, "сэрсенби": 2, "сәрсенбі": 2,
    # Четверг
    "четверг": 3, "бейсенби": 3, "бейсенбі": 3,
    # Пятница
    "пятниц": 4, "жума": 4, "жұма": 4,
    # Суббота
    "суббот": 5, "сенби": 5, "сенбі": 5,
    # Воскресенье
    "воскресень": 6, "жексенби": 6, "жексенбі": 6,
}

# Числительные словами → час (именительный/дательный, рус). Best-effort.
_WORD_HOURS: dict[str, int] = {
    "час": 1, "один": 1, "одному": 1,
    "два": 2, "двум": 2, "две": 2,
    "три": 3, "трем": 3, "трём": 3,
    "четыр": 4, "четырем": 4, "четырём": 4,
    "пят": 5, "пяти": 5,
    "шест": 6, "шести": 6,
    "сем": 7, "семи": 7,
    "восем": 8, "восьми": 8,
    "девят": 9, "девяти": 9,
    "десят": 10, "десяти": 10,
    "одиннадцат": 11,
    "двенадцат": 12,
}


def _parse_date(date_raw: Optional[str], today: datetime.date) -> Optional[datetime.date]:
    if not date_raw:
        return None
    s = date_raw.lower().strip()

    # Относительные дни (рус + каз русскими буквами).
    if any(w in s for w in ("сегодня", "бугин", "бүгін")):
        return today
    if any(w in s for w in ("послезавтра", "арги кун", "арғы күн", "бурсыгуни")):
        return today + datetime.timedelta(days=2)
    if any(w in s for w in ("завтра", "ертен", "ертең")):
        return today + datetime.timedelta(days=1)

    # Дни недели → ближайшая такая дата в будущем (если сегодня — берём через неделю).
    for stem, weekday in _WEEKDAY_STEMS.items():
        if stem in s:
            ahead = (weekday - today.weekday()) % 7
            if ahead == 0:
                ahead = 7
            return today + datetime.timedelta(days=ahead)

    # Уверенно распарсить нельзя — НЕ выдумываем. None (raw сохранён отдельно).
    return None


def _parse_time(time_raw: Optional[str]) -> Optional[datetime.time]:
    if not time_raw:
        return None
    s = time_raw.lower().strip()

    # 1) Явное HH:MM (или HH.MM).
    m = re.search(r"\b(\d{1,2})[:.](\d{2})\b", s)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return datetime.time(hour, minute)

    # 2) Число часов: «сагат 3», «в 15», «на 14», «3-ке», «к 9».
    m = re.search(r"\b(\d{1,2})\b", s)
    if m:
        hour = int(m.group(1))
        if 0 <= hour <= 23:
            return datetime.time(hour, 0)

    # 3) Числительное словами: «к трём», «на двенадцать».
    for word, hour in _WORD_HOURS.items():
        if word in s:
            return datetime.time(hour, 0)

    return None


def parse_when(
    date_raw: Optional[str],
    time_raw: Optional[str],
    today: Optional[datetime.date] = None,
) -> tuple[Optional[datetime.date], Optional[datetime.time]]:
    """Best-effort разбор сырых строк даты/времени в (date|None, time|None).

    `today` можно передать для детерминированных тестов (по умолчанию — сегодня).
    Если уверенно распарсить нельзя — возвращаем None для соответствующей части
    (raw-строку всегда хранит сам BookingRequest). Никаких выдуманных дат.
    """
    if today is None:
        today = datetime.date.today()
    return _parse_date(date_raw, today), _parse_time(time_raw)
