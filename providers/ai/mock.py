"""Mock-реализация AI-провайдера. Работает без интернета, для тестов."""
from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from .base import AIProvider, ChatMessage

if TYPE_CHECKING:
    from clinics.models import Clinic

logger = logging.getLogger(__name__)

# Простая эвристика намерения записаться — ТОЛЬКО для mock (офлайн-тесты).
# Реальное распознавание делает Groq в json_mode. Включает русские и казахские
# (русскими буквами) маркеры явного намерения записаться/прийти.
_BOOKING_MARKERS = (
    "запиш",  # записаться, запишите, запишусь
    "записа",
    "хочу прий",
    "прийти",
    "приду",
    "жазыл",  # жазылайын, жазылам (казахский — записаться)
    "келг",  # келгим келеди (хочу прийти)
)

# Маркеры дня (рус + каз русскими буквами) — для эвристики mock в json_mode.
# Реальное распознавание дня делает Groq; здесь — только офлайн-тесты слот-флоу.
_DATE_MARKERS = (
    "сегодня", "бугин",
    "послезавтра", "арги кун", "бурсыгуни",
    "завтра", "ертен",
    "понедельник", "дуйсенби",
    "вторник", "сейсенби",
    "сред", "сэрсенби",
    "четверг", "бейсенби",
    "пятниц", "жума",
    "суббот", "сенби",
    "воскрес", "жексенби",
)


def _extract_slots_mock(text: str, clinic: "Clinic") -> dict:
    """Грубое извлечение слотов из сообщения — ТОЛЬКО для mock (офлайн-тесты).

    Услугу ищем по основам слов из прайса клиники, день — по маркерам,
    время — по наличию числа часов. Реальное извлечение делает Groq.
    """
    s = (text or "").lower()
    slots: dict = {"service": None, "preferred_date_raw": None, "preferred_time_raw": None}

    # Услуга: совпадение основы (>=5 букв) любого слова из названия услуги.
    for item in getattr(clinic, "services_json", None) or []:
        name = item.get("name") if isinstance(item, dict) else None
        if not name:
            continue
        for word in str(name).lower().split():
            if len(word) >= 5 and word[:5] in s:
                slots["service"] = name
                break
        if slots["service"]:
            break

    # День: первый встретившийся маркер сохраняем как сырую строку.
    for marker in _DATE_MARKERS:
        if marker in s:
            slots["preferred_date_raw"] = marker
            break

    # Время: есть число 0–23 (например, «в 15», «15:00», «сагат 3»).
    m = re.search(r"\b(\d{1,2})(?:[:.]\d{2})?\b", s)
    if m and 0 <= int(m.group(1)) <= 23:
        slots["preferred_time_raw"] = text.strip()

    return slots


class MockAIProvider(AIProvider):
    """Возвращает детерминированные заглушки вместо вызова реального API."""

    def generate(
        self,
        messages: list[ChatMessage],
        clinic: "Clinic",
        json_mode: bool = False,
    ) -> str:
        last_user = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"),
            "",
        )
        clinic_name = getattr(clinic, "name", "клиника")
        logger.info(
            "[mock-ai] generate for %s, json_mode=%s, last user msg: %r",
            clinic_name,
            json_mode,
            last_user,
        )

        if json_mode:
            # Детерминированный «structured output»: распознаём намерение по
            # маркерам. Вопрос о цене маркеров не содержит → wants_booking=false.
            # Слоты (услуга/день/время) извлекаем грубой эвристикой, чтобы офлайн
            # можно было прогнать весь слот-флоу записи (Фаза 3, #3).
            wants = any(marker in last_user.lower() for marker in _BOOKING_MARKERS)
            slots = _extract_slots_mock(last_user, clinic)
            return json.dumps(
                {
                    "wants_booking": wants,
                    "service": slots["service"],
                    "preferred_date_raw": slots["preferred_date_raw"],
                    "preferred_time_raw": slots["preferred_time_raw"],
                    "customer_name": None,
                },
                ensure_ascii=False,
            )

        return (
            f"[mock-ответ от «{clinic_name}»] "
            f"Здравствуйте! Я получил ваше сообщение: «{last_user}». "
            "Это заглушка ответа — реальный AI подключим в следующей фазе."
        )

    def transcribe(self, audio_bytes: bytes, mimetype: str) -> str | None:
        logger.info("[mock-ai] transcribe %d bytes, mimetype=%s", len(audio_bytes), mimetype)
        return "[mock-транскрипт]"
