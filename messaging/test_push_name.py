"""
Тесты автоматического сохранения pushName + поведения бота при записи.
На MockProvider, офлайн — без сети и без реального Groq.

Проверяем:
- pushName из payload корректно сохраняется на диалоге;
- имя не затирается пустым значением при повторных сообщениях;
- при записи с известным именем бот подтверждает его («Записываю на имя X, верно?»);
- при пустом pushName бот спрашивает имя при записи («Как вас зовут?»).
"""
import pytest
from unittest.mock import patch

from bookings.flow import _QUESTIONS, handle_booking_turn
from clinics.models import Clinic
from messaging.models import Conversation
from messaging.tasks import handle_incoming_message
from providers.ai.mock import MockAIProvider
from providers.whatsapp.mock import MockWhatsAppProvider


@pytest.fixture
def clinic(db):
    return Clinic.objects.create(
        name="Тест-клиника",
        whatsapp_number="77001234567",
        services_json=[
            {"name": "Профессиональная чистка", "price": "14 000 ₸"},
        ],
    )


def _run_task(clinic, customer_phone, text, push_name="", external_id="ext-001"):
    """Запустить handle_incoming_message синхронно с mock-провайдерами."""
    with (
        patch("messaging.tasks.get_ai_provider", return_value=MockAIProvider()),
        patch("messaging.tasks.get_whatsapp_provider_for_clinic", return_value=MockWhatsAppProvider()),
    ):
        handle_incoming_message(
            clinic_number=clinic.whatsapp_number,
            customer_phone=customer_phone,
            text=text,
            external_id=external_id,
            push_name=push_name,
        )


@pytest.mark.django_db
def test_push_name_saved_on_first_message(clinic, settings):
    """pushName из payload сохраняется на диалоге при первом сообщении."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    _run_task(clinic, "77009998877", "здравствуйте", push_name="Айгерим")

    conv = Conversation.objects.get(clinic=clinic, customer_phone="77009998877")
    assert conv.customer_name == "Айгерим"


@pytest.mark.django_db
def test_push_name_not_overwritten_by_empty(clinic, settings):
    """Имя не затирается пустым pushName при повторных сообщениях."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    # Первое сообщение — устанавливаем имя
    _run_task(clinic, "77009998877", "здравствуйте", push_name="Айгерим", external_id="ext-001")

    # Второе сообщение — push_name пустой
    _run_task(clinic, "77009998877", "сколько стоит чистка?", push_name="", external_id="ext-002")

    conv = Conversation.objects.get(clinic=clinic, customer_phone="77009998877")
    assert conv.customer_name == "Айгерим"  # не затёрто


@pytest.mark.django_db
def test_booking_confirms_known_name(clinic):
    """При записи с известным именем бот подтверждает его, а не спрашивает заново."""
    conversation = Conversation.objects.create(
        clinic=clinic,
        customer_phone="77009998877",
        customer_name="Айгерим",
    )
    ai = MockAIProvider()

    # Все три основных слота в одном сообщении → бот должен запросить подтверждение имени
    reply = handle_booking_turn(
        conversation, "запишите на чистку завтра в 15", clinic, ai=ai
    )

    assert reply is not None
    assert "Айгерим" in reply
    assert "верно" in reply.lower()
    assert conversation.booking_stage == Conversation.BookingStage.COLLECTING
    assert conversation.booking_draft.get("_name_pending_confirm") is True


@pytest.mark.django_db
def test_booking_asks_name_when_unknown(clinic):
    """При пустом pushName бот спрашивает имя как часть заявки."""
    conversation = Conversation.objects.create(
        clinic=clinic,
        customer_phone="77009998877",
        # customer_name не задан
    )
    ai = MockAIProvider()

    # Все три основных слота → бот должен спросить имя
    reply = handle_booking_turn(
        conversation, "запишите на чистку завтра в 15", clinic, ai=ai
    )

    assert reply == _QUESTIONS["name"]
    assert conversation.booking_stage == Conversation.BookingStage.COLLECTING


@pytest.mark.django_db
def test_name_confirmation_accepted(clinic):
    """Пациент подтверждает имя («да») → stage=READY, имя сохранено."""
    conversation = Conversation.objects.create(
        clinic=clinic,
        customer_phone="77009998877",
        customer_name="Айгерим",
        booking_stage=Conversation.BookingStage.COLLECTING,
        booking_draft={
            "service": "Профессиональная чистка",
            "preferred_date_raw": "завтра",
            "preferred_time_raw": "в 15",
            "customer_name": "Айгерим",
            "_name_pending_confirm": True,
        },
    )
    ai = MockAIProvider()

    # Пациент говорит «да» — нет нового имени → сохраняем «Айгерим»
    reply = handle_booking_turn(conversation, "да, верно", clinic, ai=ai)

    assert reply is None
    assert conversation.booking_stage == Conversation.BookingStage.READY
    assert conversation.booking_draft.get("customer_name") == "Айгерим"
    assert "_name_pending_confirm" not in conversation.booking_draft


@pytest.mark.django_db
def test_name_confirmation_corrected(clinic):
    """Пациент называет другое имя → обновляется в черновике и диалоге."""
    conversation = Conversation.objects.create(
        clinic=clinic,
        customer_phone="77009998877",
        customer_name="Айгерим",
        booking_stage=Conversation.BookingStage.COLLECTING,
        booking_draft={
            "service": "Профессиональная чистка",
            "preferred_date_raw": "завтра",
            "preferred_time_raw": "в 15",
            "customer_name": "Айгерим",
            "_name_pending_confirm": True,
        },
    )
    ai = MockAIProvider()

    # Пациент называет другое имя
    reply = handle_booking_turn(conversation, "нет, меня зовут Алия", clinic, ai=ai)

    assert reply is None
    assert conversation.booking_stage == Conversation.BookingStage.READY
    assert conversation.booking_draft.get("customer_name") == "Алия"
    assert "_name_pending_confirm" not in conversation.booking_draft
    # Имя обновилось и на диалоге
    conversation.refresh_from_db()
    assert conversation.customer_name == "Алия"
