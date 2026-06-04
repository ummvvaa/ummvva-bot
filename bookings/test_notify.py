"""
Тесты Celery-задачи notify_manager (Фаза 3, Промпт #5).
На MockProvider, офлайн — без сети и без реального WhatsApp.

Проверяем:
- заявка с заполненным manager_whatsapp → провайдер получил один вызов send_message
  с текстом, содержащим #id и услугу; status → "notified";
- notifications_enabled=False → send НЕ вызывается, status остаётся "new";
- пустой manager_whatsapp → send НЕ вызывается, без падения.
"""
import pytest
from unittest.mock import patch

from bookings.models import BookingRequest
from bookings.tasks import notify_manager
from clinics.models import Clinic
from messaging.models import Conversation
from providers.whatsapp.mock import MockWhatsAppProvider


@pytest.fixture
def clinic(db):
    return Clinic.objects.create(
        name="Жемчуг Дент",
        whatsapp_number="77001112233",
        manager_whatsapp="77000000001",
        notifications_enabled=True,
    )


@pytest.fixture
def conversation(clinic):
    return Conversation.objects.create(clinic=clinic, customer_phone="77009998877")


@pytest.fixture
def booking(conversation):
    return BookingRequest.objects.create(
        clinic=conversation.clinic,
        conversation=conversation,
        customer_phone=conversation.customer_phone,
        customer_name="Айгерим",
        service="Профессиональная чистка",
        preferred_date_raw="завтра",
        preferred_time_raw="в 15",
        status=BookingRequest.Status.NEW,
    )


@pytest.mark.django_db
def test_notify_manager_sends_and_marks_notified(booking):
    mock_provider = MockWhatsAppProvider()
    with patch("bookings.tasks.get_whatsapp_provider_for_clinic", return_value=mock_provider):
        notify_manager.apply(args=[booking.id])

    # Провайдер получил ровно один вызов send_message
    assert len(mock_provider.sent) == 1
    sent = mock_provider.sent[0]

    # Сообщение направлено на номер менеджера
    assert sent["to"] == booking.clinic.manager_whatsapp

    # Текст содержит id заявки и услугу
    assert f"#{booking.id}" in sent["text"]
    assert "Профессиональная чистка" in sent["text"]

    # Статус перешёл в notified
    booking.refresh_from_db()
    assert booking.status == BookingRequest.Status.NOTIFIED


@pytest.mark.django_db
def test_notify_manager_skips_when_disabled(booking):
    booking.clinic.notifications_enabled = False
    booking.clinic.save()

    mock_provider = MockWhatsAppProvider()
    with patch("bookings.tasks.get_whatsapp_provider_for_clinic", return_value=mock_provider):
        notify_manager.apply(args=[booking.id])

    # send не вызывался
    assert len(mock_provider.sent) == 0

    # Статус остался new
    booking.refresh_from_db()
    assert booking.status == BookingRequest.Status.NEW


@pytest.mark.django_db
def test_notify_manager_skips_when_no_manager_number(booking):
    booking.clinic.manager_whatsapp = None
    booking.clinic.save()

    mock_provider = MockWhatsAppProvider()
    with patch("bookings.tasks.get_whatsapp_provider_for_clinic", return_value=mock_provider):
        notify_manager.apply(args=[booking.id])

    # send не вызывался, задача не упала
    assert len(mock_provider.sent) == 0
    booking.refresh_from_db()
    assert booking.status == BookingRequest.Status.NEW
