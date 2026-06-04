"""
Тесты создания заявки (finalize_booking) и интеграции с Celery-таской (Фаза 3, Промпт #4).
На MockProvider, офлайн — без сети и без реального Groq.

Проверяем:
- готовый черновик → finalize_booking создаёт ровно одну BookingRequest,
  stage сбрасывается в none, draft очищается;
- повторный finalize в окне дедупа → вторая заявка НЕ создаётся, первая обновляется;
- обычный вопрос о цене проходит мимо записи и идёт в AI-флоу (нет BookingRequest,
  ответ от MockAIProvider сохранён в БД).
"""
import pytest
from unittest.mock import patch

from bookings.flow import finalize_booking
from bookings.models import BookingRequest
from clinics.models import Clinic
from messaging.models import Conversation, Message
from providers.ai.mock import MockAIProvider
from providers.whatsapp.mock import MockWhatsAppProvider


@pytest.fixture
def clinic(db):
    return Clinic.objects.create(
        name="Жемчуг Дент",
        whatsapp_number="77001112233",
        services_json=[
            {"name": "Профессиональная чистка", "price": "14 000 ₸"},
        ],
    )


@pytest.fixture
def conversation(clinic):
    return Conversation.objects.create(clinic=clinic, customer_phone="77009998877")


def _set_ready_draft(conversation):
    """Выставить черновик в состояние ready (все слоты собраны)."""
    conversation.booking_stage = Conversation.BookingStage.READY
    conversation.booking_draft = {
        "service": "Профессиональная чистка",
        "preferred_date_raw": "завтра",
        "preferred_time_raw": "в 15",
        "preferred_date": "2026-06-05",
        "preferred_time": "15:00:00",
        "customer_name": "Айгерим",
    }
    conversation.save()


@pytest.mark.django_db
def test_finalize_creates_booking_and_resets_state(conversation):
    _set_ready_draft(conversation)

    booking = finalize_booking(conversation, conversation.clinic)

    # Ровно одна заявка в БД
    assert BookingRequest.objects.filter(conversation=conversation).count() == 1
    assert booking.pk is not None

    # Данные слотов перенесены
    assert booking.service == "Профессиональная чистка"
    assert booking.preferred_date_raw == "завтра"
    assert booking.preferred_time_raw == "в 15"
    assert str(booking.preferred_date) == "2026-06-05"
    assert str(booking.preferred_time) == "15:00:00"
    assert booking.status == BookingRequest.Status.NEW
    assert booking.clinic == conversation.clinic

    # ПДн: телефон записан (шифруется, через ORM читается)
    booking.refresh_from_db()
    assert booking.customer_phone == conversation.customer_phone
    assert booking.customer_name == "Айгерим"

    # Состояние сброшено
    conversation.refresh_from_db()
    assert conversation.booking_stage == Conversation.BookingStage.NONE
    assert conversation.booking_draft == {}


@pytest.mark.django_db
def test_dedup_updates_existing_within_window(conversation):
    _set_ready_draft(conversation)

    # Первый finalize — создаёт заявку
    booking1 = finalize_booking(conversation, conversation.clinic)
    assert BookingRequest.objects.filter(conversation=conversation).count() == 1

    # Ставим черновик снова (stage сбросился, симулируем новый сбор)
    conversation.booking_stage = Conversation.BookingStage.READY
    conversation.booking_draft = {
        "service": "Отбеливание ZOOM 4",
        "preferred_date_raw": "послезавтра",
        "preferred_time_raw": "в 11",
        "preferred_date": "2026-06-06",
        "preferred_time": "11:00:00",
    }
    conversation.save()

    # Второй finalize в том же окне — должен ОБНОВИТЬ первую, не создать вторую
    booking2 = finalize_booking(conversation, conversation.clinic)

    assert BookingRequest.objects.filter(conversation=conversation).count() == 1
    assert booking2.pk == booking1.pk  # тот же объект

    booking2.refresh_from_db()
    assert booking2.service == "Отбеливание ZOOM 4"
    assert booking2.preferred_date_raw == "послезавтра"


@pytest.mark.django_db
def test_price_question_goes_to_ai_flow(clinic, settings):
    """Вопрос о цене НЕ создаёт BookingRequest — идёт в обычный AI-флоу."""
    settings.CELERY_TASK_ALWAYS_EAGER = True

    from messaging.tasks import handle_incoming_message

    with (
        patch("messaging.tasks.get_ai_provider", return_value=MockAIProvider()),
        patch("messaging.tasks.get_whatsapp_provider_for_clinic", return_value=MockWhatsAppProvider()),
    ):
        handle_incoming_message(
            clinic_number="77001112233",
            customer_phone="77009998877",
            text="сколько стоит чистка?",
            external_id="ext-price-001",
        )

    # Заявок нет — вопрос о цене не запись
    assert BookingRequest.objects.filter(conversation__customer_phone="77009998877").count() == 0

    # Диалог создан, ответ бота сохранён в БД
    conv = Conversation.objects.get(clinic=clinic, customer_phone="77009998877")
    messages = list(conv.messages.all())
    assert len(messages) == 2
    assert messages[0].role == Message.Role.USER
    assert messages[1].role == Message.Role.ASSISTANT
    # stage не изменилась
    assert conv.booking_stage == Conversation.BookingStage.NONE
