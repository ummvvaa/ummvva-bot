"""
Тесты ветки менеджера и замыкания цикла «решение менеджера → уведомление пациента»
(Фаза 3, Промпт #6). На MockProvider, офлайн — без сети и без реального WhatsApp.

Проверяем:
- "+{id}" от номера менеджера клиники → status="confirmed", пациенту ушло ОДНО
  подтверждение; новая переписка/заявка НЕ создана;
- "-{id}" → status="rejected", пациенту ушёл мягкий отказ;
- менеджер пытается тронуть заявку ЧУЖОЙ клиники → игнор, статус не меняется;
- смена статуса в admin на "confirmed" → notify_customer вызван один раз;
- обычное пациентское сообщение по-прежнему идёт в пациентский флоу.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.admin.sites import AdminSite

from bookings.admin import BookingRequestAdmin
from bookings.models import BookingRequest
from clinics.models import Clinic
from messaging.models import Conversation, Message
from providers.ai.mock import MockAIProvider
from providers.whatsapp.mock import MockWhatsAppProvider


MANAGER_PHONE = "77000000001"
CUSTOMER_PHONE = "77009998877"


@pytest.fixture
def clinic(db):
    return Clinic.objects.create(
        name="Жемчуг Дент",
        whatsapp_number="77001112233",
        manager_whatsapp=MANAGER_PHONE,
        notifications_enabled=True,
        services_json=[{"name": "Профессиональная чистка", "price": "14 000 ₸"}],
    )


@pytest.fixture
def conversation(clinic):
    return Conversation.objects.create(clinic=clinic, customer_phone=CUSTOMER_PHONE)


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
        status=BookingRequest.Status.NOTIFIED,
    )


def _run_manager_message(text, clinic, mock_provider):
    """Прогнать сообщение от номера менеджера через handle_incoming_message.

    Один и тот же mock-провайдер используется и для ответа менеджеру
    (messaging.tasks), и для уведомления пациента (bookings.tasks) — все
    отправки складываются в mock_provider.sent.
    """
    from messaging.tasks import handle_incoming_message

    with (
        patch("messaging.tasks.get_whatsapp_provider", return_value=mock_provider),
        patch("bookings.tasks.get_whatsapp_provider", return_value=mock_provider),
    ):
        handle_incoming_message(
            clinic_number=clinic.whatsapp_number,
            customer_phone=clinic.manager_whatsapp,
            text=text,
            external_id="mgr-ext-001",
        )


@pytest.mark.django_db
def test_manager_confirm_notifies_customer_once(booking, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    clinic = booking.clinic
    mock_provider = MockWhatsAppProvider()

    conv_before = Conversation.objects.count()
    booking_before = BookingRequest.objects.count()

    _run_manager_message(f"+{booking.id}", clinic, mock_provider)

    # Заявка подтверждена
    booking.refresh_from_db()
    assert booking.status == BookingRequest.Status.CONFIRMED

    # Новая переписка/заявка НЕ создана (номер менеджера не пациент)
    assert Conversation.objects.count() == conv_before
    assert BookingRequest.objects.count() == booking_before
    assert not Conversation.objects.filter(customer_phone=MANAGER_PHONE).exists()

    # Пациенту ушло РОВНО одно подтверждение
    to_customer = [m for m in mock_provider.sent if m["to"] == CUSTOMER_PHONE]
    assert len(to_customer) == 1
    assert "подтверждена" in to_customer[0]["text"]
    assert clinic.name in to_customer[0]["text"]


@pytest.mark.django_db
def test_manager_confirm_with_note(booking, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    clinic = booking.clinic
    mock_provider = MockWhatsAppProvider()

    _run_manager_message(f"+{booking.id} приходите к 16:00", clinic, mock_provider)

    booking.refresh_from_db()
    assert booking.status == BookingRequest.Status.CONFIRMED
    assert booking.manager_note == "приходите к 16:00"

    to_customer = [m for m in mock_provider.sent if m["to"] == CUSTOMER_PHONE]
    assert len(to_customer) == 1
    assert "приходите к 16:00" in to_customer[0]["text"]


@pytest.mark.django_db
def test_manager_reject_sends_soft_notice(booking, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    clinic = booking.clinic
    mock_provider = MockWhatsAppProvider()

    _run_manager_message(f"-{booking.id}", clinic, mock_provider)

    booking.refresh_from_db()
    assert booking.status == BookingRequest.Status.REJECTED

    to_customer = [m for m in mock_provider.sent if m["to"] == CUSTOMER_PHONE]
    assert len(to_customer) == 1
    # Мягкий отказ: без негатива, предлагаем уточнить время
    assert "уточнить время" in to_customer[0]["text"]


@pytest.mark.django_db
def test_manager_cannot_touch_foreign_clinic_booking(booking, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True

    # Вторая клиника со своим менеджером.
    other_clinic = Clinic.objects.create(
        name="Дента Плюс",
        whatsapp_number="77002223344",
        manager_whatsapp="77000000002",
        notifications_enabled=True,
    )
    mock_provider = MockWhatsAppProvider()

    # Менеджер чужой клиники пытается подтвердить заявку booking (клиника №1).
    from messaging.tasks import handle_incoming_message

    with (
        patch("messaging.tasks.get_whatsapp_provider", return_value=mock_provider),
        patch("bookings.tasks.get_whatsapp_provider", return_value=mock_provider),
    ):
        handle_incoming_message(
            clinic_number=other_clinic.whatsapp_number,
            customer_phone=other_clinic.manager_whatsapp,
            text=f"+{booking.id}",
            external_id="mgr-ext-foreign",
        )

    # Статус НЕ изменился, пациенту ничего не ушло
    booking.refresh_from_db()
    assert booking.status == BookingRequest.Status.NOTIFIED
    assert not [m for m in mock_provider.sent if m["to"] == CUSTOMER_PHONE]


@pytest.mark.django_db
def test_manager_unknown_command_gets_hint(clinic, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    mock_provider = MockWhatsAppProvider()

    _run_manager_message("привет, как дела?", clinic, mock_provider)

    # Менеджеру ушла подсказка по формату
    to_manager = [m for m in mock_provider.sent if m["to"] == MANAGER_PHONE]
    assert len(to_manager) == 1
    assert "+номер" in to_manager[0]["text"] or "«+12»" in to_manager[0]["text"]


@pytest.mark.django_db
def test_admin_status_change_notifies_customer_once(booking):
    """Путь (Б): смена статуса в admin → notify_customer вызван ровно один раз."""
    admin_obj = BookingRequestAdmin(BookingRequest, AdminSite())
    booking.status = BookingRequest.Status.CONFIRMED
    form = SimpleNamespace(changed_data=["status"])

    with patch("bookings.admin.notify_customer") as mock_task:
        admin_obj.save_model(request=None, obj=booking, form=form, change=True)

    mock_task.delay.assert_called_once_with(booking.id)

    # Без смены статуса (правка только заметки) — уведомление не шлётся.
    form_no_status = SimpleNamespace(changed_data=["manager_note"])
    with patch("bookings.admin.notify_customer") as mock_task2:
        admin_obj.save_model(request=None, obj=booking, form=form_no_status, change=True)
    mock_task2.delay.assert_not_called()


@pytest.mark.django_db
def test_patient_message_still_goes_to_patient_flow(clinic, settings):
    """Обычное пациентское сообщение по-прежнему идёт в пациентский флоу."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    mock_provider = MockWhatsAppProvider()

    from messaging.tasks import handle_incoming_message

    with (
        patch("messaging.tasks.get_ai_provider", return_value=MockAIProvider()),
        patch("messaging.tasks.get_whatsapp_provider", return_value=mock_provider),
    ):
        handle_incoming_message(
            clinic_number=clinic.whatsapp_number,
            customer_phone=CUSTOMER_PHONE,
            text="сколько стоит чистка?",
            external_id="patient-ext-001",
        )

    # Пациентский диалог создан, есть user+assistant сообщения
    conv = Conversation.objects.get(clinic=clinic, customer_phone=CUSTOMER_PHONE)
    roles = list(conv.messages.values_list("role", flat=True))
    assert Message.Role.USER in roles
    assert Message.Role.ASSISTANT in roles

    # Ответ ушёл пациенту
    assert [m for m in mock_provider.sent if m["to"] == CUSTOMER_PHONE]
