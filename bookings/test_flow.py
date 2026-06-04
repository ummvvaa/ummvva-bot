"""
Тесты диалога записи (слот-филлинг, Фаза 3, Промпт #3).
На MockProvider, офлайн — без сети и без реального Groq.

Проверяем:
- полный сбор услуга → день → время по одному вопросу за раз, без потери собранного;
- вопрос о цене не запускает запись (handle_booking_turn → None);
- частичная заявка дозапрашивает только недостающее;
- анти-тупик: 2 нерелевантных ответа подряд → stage="ready" с частичными данными.
"""
import pytest

from bookings.flow import _HANDOFF_REPLY, _QUESTIONS, handle_booking_turn
from clinics.models import Clinic
from messaging.models import Conversation
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


@pytest.fixture
def conversation(clinic):
    return Conversation.objects.create(clinic=clinic, customer_phone="77009998877")


def _turn(conversation, text):
    """Один ход диалога на mock-провайдере (офлайн)."""
    return handle_booking_turn(conversation, text, conversation.clinic, ai=MockAIProvider())


@pytest.mark.django_db
def test_full_slot_filling_flow(conversation):
    # "хочу записаться" — услуги/дня/времени нет → спрашиваем услугу.
    reply = _turn(conversation, "хочу записаться")
    assert reply == _QUESTIONS["service"]
    assert conversation.booking_stage == Conversation.BookingStage.COLLECTING

    # "чистка" → услуга собрана, спрашиваем день.
    reply = _turn(conversation, "чистка")
    assert reply == _QUESTIONS["date"]
    assert conversation.booking_draft["service"]  # уже не теряем услугу

    # "завтра" → день собран, спрашиваем время.
    reply = _turn(conversation, "завтра")
    assert reply == _QUESTIONS["time"]

    # "в 15" → основные слоты собраны, имя неизвестно → спрашиваем имя.
    reply = _turn(conversation, "в 15")
    assert reply == _QUESTIONS["name"]
    assert conversation.booking_stage == Conversation.BookingStage.COLLECTING

    # "меня зовут Иван" → имя собрано → ready.
    reply = _turn(conversation, "меня зовут Иван")
    assert reply is None
    assert conversation.booking_stage == Conversation.BookingStage.READY

    draft = conversation.booking_draft
    assert draft["service"]
    assert draft["preferred_date_raw"] == "завтра"
    assert draft["preferred_time_raw"] == "в 15"
    assert draft["customer_name"] == "Иван"
    # Время распарсилось best-effort; день — относительный, тоже распарсился.
    assert draft["preferred_time"] == "15:00:00"
    assert draft["preferred_date"] is not None


@pytest.mark.django_db
def test_price_question_is_not_booking(conversation):
    # Вопрос о цене — это НЕ запись: обычный флоу Фазы 1 (вернуть None, не трогать стадию).
    reply = _turn(conversation, "сколько стоит чистка?")
    assert reply is None
    assert conversation.booking_stage == Conversation.BookingStage.NONE


@pytest.mark.django_db
def test_partial_booking_asks_only_missing_slot(conversation):
    # Услуга и день названы сразу → дозапрашиваем ТОЛЬКО время.
    reply = _turn(conversation, "запишите на чистку завтра")
    assert reply == _QUESTIONS["time"]
    assert conversation.booking_stage == Conversation.BookingStage.COLLECTING
    assert conversation.booking_draft["service"]
    assert conversation.booking_draft["preferred_date_raw"] == "завтра"


@pytest.mark.django_db
def test_anti_deadlock_hands_off_after_two_misses(conversation):
    # Старт: услуга названа, дальше пациент дважды отвечает не по теме (нет дня).
    reply = _turn(conversation, "запишите на чистку")
    assert reply == _QUESTIONS["date"]

    # 1-й промах — ещё переспрашиваем.
    reply = _turn(conversation, "ой не помню")
    assert reply == _QUESTIONS["date"]
    assert conversation.booking_stage == Conversation.BookingStage.COLLECTING

    # 2-й промах подряд — не зацикливаемся: отдаём менеджеру что есть.
    reply = _turn(conversation, "потом скажу")
    assert reply == _HANDOFF_REPLY
    assert conversation.booking_stage == Conversation.BookingStage.READY
    # Частичные данные сохранены (услуга есть, дня нет).
    assert conversation.booking_draft["service"]
    assert not conversation.booking_draft.get("preferred_date_raw")
