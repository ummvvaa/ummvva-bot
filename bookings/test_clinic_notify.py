"""
Тесты изоляции уведомлений по клиникам (Фаза 3 + Фаза 4).
На MockProvider, офлайн.

Проверяем:
- notify_manager отправляет через провайдер ИМЕННО той клиники, к которой
  относится заявка; провайдер клиники Б при заявке клиники А не вызывается;
- notify_customer уведомляет пациента через провайдер его клиники, провайдер
  другой клиники не трогается;
- менеджер клиники А не может подтвердить/отклонить заявку клиники Б
  (матчинг по clinic_id + booking_id).
"""
from unittest.mock import patch

import pytest

from bookings.models import BookingRequest
from bookings.tasks import notify_customer, notify_manager
from clinics.models import Clinic
from messaging.models import Conversation
from messaging.tasks import handle_incoming_message
from providers.whatsapp.mock import MockWhatsAppProvider


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def clinic_a(db):
    return Clinic.objects.create(
        name="Клиника А",
        whatsapp_number="77001111111",
        instance_name="clinic-a",
        manager_whatsapp="77010000001",
        notifications_enabled=True,
        services_json=[{"name": "Чистка", "price": "10 000 ₸"}],
    )


@pytest.fixture
def clinic_b(db):
    return Clinic.objects.create(
        name="Клиника Б",
        whatsapp_number="77002222222",
        instance_name="clinic-b",
        manager_whatsapp="77020000002",
        notifications_enabled=True,
        services_json=[{"name": "Имплант", "price": "150 000 ₸"}],
    )


@pytest.fixture
def booking_a(clinic_a):
    conv = Conversation.objects.create(clinic=clinic_a, customer_phone="77099000001")
    return BookingRequest.objects.create(
        clinic=clinic_a,
        conversation=conv,
        customer_phone=conv.customer_phone,
        service="Чистка",
        preferred_date_raw="завтра",
        preferred_time_raw="в 14",
        status=BookingRequest.Status.NEW,
    )


@pytest.fixture
def booking_b(clinic_b):
    conv = Conversation.objects.create(clinic=clinic_b, customer_phone="77099000002")
    return BookingRequest.objects.create(
        clinic=clinic_b,
        conversation=conv,
        customer_phone=conv.customer_phone,
        service="Имплант",
        preferred_date_raw="послезавтра",
        preferred_time_raw="в 10",
        status=BookingRequest.Status.NOTIFIED,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _providers_by_clinic(clinic_a, provider_a, clinic_b, provider_b):
    """Фабрика side_effect: возвращает нужный mock-провайдер по клинике."""
    def _dispatch(clinic):
        if clinic.id == clinic_a.id:
            return provider_a
        if clinic.id == clinic_b.id:
            return provider_b
        return MockWhatsAppProvider()
    return _dispatch


# ---------------------------------------------------------------------------
# notify_manager
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_notify_manager_uses_clinic_a_provider(booking_a, clinic_a, clinic_b):
    """notify_manager использует провайдер клиники А и не трогает провайдер клиники Б."""
    provider_a = MockWhatsAppProvider()
    provider_b = MockWhatsAppProvider()
    dispatch = _providers_by_clinic(clinic_a, provider_a, clinic_b, provider_b)

    with patch("bookings.tasks.get_whatsapp_provider_for_clinic", side_effect=dispatch):
        notify_manager.apply(args=[booking_a.id])

    # Уведомление ушло через провайдер клиники А на номер менеджера А
    assert len(provider_a.sent) == 1
    assert provider_a.sent[0]["to"] == clinic_a.manager_whatsapp
    assert f"#{booking_a.id}" in provider_a.sent[0]["text"]

    # Провайдер клиники Б не получил ни одного вызова
    assert len(provider_b.sent) == 0

    booking_a.refresh_from_db()
    assert booking_a.status == BookingRequest.Status.NOTIFIED


@pytest.mark.django_db
def test_notify_manager_clinic_b_does_not_use_clinic_a_provider(booking_b, clinic_a, clinic_b):
    """notify_manager для заявки клиники Б не задействует провайдер клиники А."""
    booking_b.status = BookingRequest.Status.NEW
    booking_b.save(update_fields=["status", "updated_at"])

    provider_a = MockWhatsAppProvider()
    provider_b = MockWhatsAppProvider()
    dispatch = _providers_by_clinic(clinic_a, provider_a, clinic_b, provider_b)

    with patch("bookings.tasks.get_whatsapp_provider_for_clinic", side_effect=dispatch):
        notify_manager.apply(args=[booking_b.id])

    # Провайдер клиники А молчит
    assert len(provider_a.sent) == 0

    # Провайдер клиники Б получил уведомление на менеджера Б
    assert len(provider_b.sent) == 1
    assert provider_b.sent[0]["to"] == clinic_b.manager_whatsapp


# ---------------------------------------------------------------------------
# notify_customer
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_notify_customer_uses_clinic_a_provider(booking_a, clinic_a, clinic_b):
    """notify_customer отправляет пациенту через провайдер его клиники (А), не клиники Б."""
    booking_a.status = BookingRequest.Status.CONFIRMED
    booking_a.save(update_fields=["status", "updated_at"])

    provider_a = MockWhatsAppProvider()
    provider_b = MockWhatsAppProvider()
    dispatch = _providers_by_clinic(clinic_a, provider_a, clinic_b, provider_b)

    with patch("bookings.tasks.get_whatsapp_provider_for_clinic", side_effect=dispatch):
        notify_customer.apply(args=[booking_a.id])

    # Пациент получил подтверждение через провайдер клиники А
    assert len(provider_a.sent) == 1
    assert provider_a.sent[0]["to"] == booking_a.customer_phone
    assert "подтверждена" in provider_a.sent[0]["text"]
    assert clinic_a.name in provider_a.sent[0]["text"]

    # Провайдер клиники Б не трогался
    assert len(provider_b.sent) == 0


# ---------------------------------------------------------------------------
# Полный цикл: ответ менеджера А не затрагивает заявку клиники Б
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_manager_a_response_does_not_affect_clinic_b_booking(
    booking_a, booking_b, clinic_a, clinic_b, settings
):
    """Менеджер А не может подтвердить/отклонить заявку клиники Б.

    Матчинг по (clinic_id + booking_id): команда «+booking_b.id» от менеджера А
    распознаётся как попытка тронуть чужую заявку — игнорируется, статус Б не меняется,
    пациент Б не уведомляется.
    """
    settings.CELERY_TASK_ALWAYS_EAGER = True

    provider_a = MockWhatsAppProvider()
    provider_b = MockWhatsAppProvider()
    dispatch = _providers_by_clinic(clinic_a, provider_a, clinic_b, provider_b)

    with (
        patch("messaging.tasks.get_whatsapp_provider_for_clinic", side_effect=dispatch),
        patch("bookings.tasks.get_whatsapp_provider_for_clinic", side_effect=dispatch),
    ):
        handle_incoming_message(
            clinic_number=clinic_a.whatsapp_number,
            customer_phone=clinic_a.manager_whatsapp,
            text=f"+{booking_b.id}",
            external_id="cross-clinic-mgr-001",
        )

    # Заявка Б не изменилась
    booking_b.refresh_from_db()
    assert booking_b.status == BookingRequest.Status.NOTIFIED

    # Пациенту Б ничего не ушло
    customer_b_phone = booking_b.customer_phone
    assert not [m for m in provider_a.sent if m["to"] == customer_b_phone]
    assert not [m for m in provider_b.sent if m["to"] == customer_b_phone]


@pytest.mark.django_db
def test_manager_a_confirms_own_clinic_booking(
    booking_a, booking_b, clinic_a, clinic_b, settings
):
    """Менеджер А успешно подтверждает заявку своей клиники; заявка клиники Б не трогается."""
    settings.CELERY_TASK_ALWAYS_EAGER = True

    booking_a.status = BookingRequest.Status.NOTIFIED
    booking_a.save(update_fields=["status", "updated_at"])

    provider_a = MockWhatsAppProvider()
    provider_b = MockWhatsAppProvider()
    dispatch = _providers_by_clinic(clinic_a, provider_a, clinic_b, provider_b)

    with (
        patch("messaging.tasks.get_whatsapp_provider_for_clinic", side_effect=dispatch),
        patch("bookings.tasks.get_whatsapp_provider_for_clinic", side_effect=dispatch),
    ):
        handle_incoming_message(
            clinic_number=clinic_a.whatsapp_number,
            customer_phone=clinic_a.manager_whatsapp,
            text=f"+{booking_a.id}",
            external_id="own-clinic-mgr-001",
        )

    # Заявка А подтверждена
    booking_a.refresh_from_db()
    assert booking_a.status == BookingRequest.Status.CONFIRMED

    # Пациент А получил подтверждение через провайдер клиники А
    customer_a_phone = booking_a.customer_phone
    customer_a_msgs = [m for m in provider_a.sent if m["to"] == customer_a_phone]
    assert len(customer_a_msgs) == 1
    assert "подтверждена" in customer_a_msgs[0]["text"]

    # Заявка Б не тронута
    booking_b.refresh_from_db()
    assert booking_b.status == BookingRequest.Status.NOTIFIED

    # Провайдер клиники Б не получил сообщений пациентам
    assert not [m for m in provider_b.sent if m["to"] == booking_b.customer_phone]
