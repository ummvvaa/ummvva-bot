"""
Тесты распознавания намерения записи и парсинга слотов (Фаза 3).
На MockProvider, офлайн — без сети и без реального Groq.

Проверяем:
- extract_booking_intent возвращает dict с нужными ключами и булевым wants_booking;
- кривой JSON от провайдера → безопасный fallback, без исключения наружу;
- parse_when парсит «завтра», день недели, «в 15:00»; для мусора — (None, None).
"""
import datetime

import pytest

from bookings.extraction import _EMPTY_RESULT, extract_booking_intent, parse_when
from clinics.models import Clinic
from providers.ai.base import AIProvider, ChatMessage
from providers.ai.mock import MockAIProvider


@pytest.fixture
def clinic(db):
    return Clinic.objects.create(
        name="Тест-клиника",
        whatsapp_number="77001234567",
        services_json=[
            {"name": "Профессиональная чистка", "price": "14 000 ₸"},
            {"name": "Отбеливание ZOOM 4", "price": "65 000 ₸"},
        ],
    )


class _BrokenJSONProvider(AIProvider):
    """Провайдер, который в json_mode возвращает невалидный JSON."""

    def generate(self, messages, clinic, json_mode: bool = False) -> str:
        return "Конечно! Вот данные: {wants_booking: yes, без кавычек..."

    def transcribe(self, audio_bytes: bytes, mimetype: str):
        return None


@pytest.mark.django_db
def test_extract_returns_dict_with_required_keys(clinic):
    result = extract_booking_intent("Хочу записаться на чистку", clinic, ai=MockAIProvider())

    assert isinstance(result, dict)
    assert set(result.keys()) == set(_EMPTY_RESULT.keys())
    assert isinstance(result["wants_booking"], bool)


@pytest.mark.django_db
def test_booking_intent_detected(clinic):
    # Mock-эвристика ловит маркер «запиш».
    result = extract_booking_intent("Запишите меня на завтра", clinic, ai=MockAIProvider())
    assert result["wants_booking"] is True


@pytest.mark.django_db
def test_price_question_is_not_booking(clinic):
    # Вопрос о цене — НЕ заявка (маркеров записи нет).
    result = extract_booking_intent("Сколько стоит чистка?", clinic, ai=MockAIProvider())
    assert result["wants_booking"] is False


@pytest.mark.django_db
def test_kazakh_booking_intent(clinic):
    # Казахский русскими буквами: «жазылайын» = записаться.
    result = extract_booking_intent("Жазылайын дегем", clinic, ai=MockAIProvider())
    assert result["wants_booking"] is True


@pytest.mark.django_db
def test_broken_json_safe_fallback(clinic):
    # Кривой JSON не должен ронять флоу — безопасный fallback.
    result = extract_booking_intent("Хочу записаться", clinic, ai=_BrokenJSONProvider())

    assert isinstance(result, dict)
    assert set(result.keys()) == set(_EMPTY_RESULT.keys())
    assert result["wants_booking"] is False
    assert result["service"] is None


@pytest.mark.django_db
def test_provider_exception_safe_fallback(clinic):
    class _BoomProvider(AIProvider):
        def generate(self, messages, clinic, json_mode: bool = False) -> str:
            raise RuntimeError("сеть упала")

        def transcribe(self, audio_bytes, mimetype):
            return None

    result = extract_booking_intent("Запишите меня", clinic, ai=_BoomProvider())
    assert result == dict(_EMPTY_RESULT)


# --- parse_when -------------------------------------------------------------

# Фиксированная «сегодня» = среда 2026-06-03 для детерминизма.
_TODAY = datetime.date(2026, 6, 3)  # weekday()==2 (среда)


def test_parse_when_tomorrow():
    date, time = parse_when("завтра", None, today=_TODAY)
    assert date == datetime.date(2026, 6, 4)
    assert time is None


def test_parse_when_kazakh_tomorrow():
    date, _ = parse_when("ертен", None, today=_TODAY)
    assert date == datetime.date(2026, 6, 4)


def test_parse_when_today():
    date, _ = parse_when("сегодня", None, today=_TODAY)
    assert date == _TODAY


def test_parse_when_weekday():
    # Ближайшая суббота после среды 2026-06-03 → 2026-06-06.
    date, _ = parse_when("в субботу", None, today=_TODAY)
    assert date == datetime.date(2026, 6, 6)


def test_parse_when_weekday_kazakh():
    # «сенби» = суббота.
    date, _ = parse_when("сенбиде", None, today=_TODAY)
    assert date == datetime.date(2026, 6, 6)


def test_parse_when_time_hhmm():
    _, time = parse_when(None, "в 15:00", today=_TODAY)
    assert time == datetime.time(15, 0)


def test_parse_when_time_kazakh_hour():
    # «сагат 3-ке» = к 3 часам.
    _, time = parse_when(None, "сагат 3-ке", today=_TODAY)
    assert time == datetime.time(3, 0)


def test_parse_when_time_word():
    _, time = parse_when(None, "к трём", today=_TODAY)
    assert time == datetime.time(3, 0)


def test_parse_when_garbage_returns_none():
    assert parse_when("когда-нибудь потом", "не знаю", today=_TODAY) == (None, None)


def test_parse_when_both_none():
    assert parse_when(None, None, today=_TODAY) == (None, None)
