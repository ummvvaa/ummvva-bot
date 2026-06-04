"""
ДОКАЗАТЕЛЬСТВО изоляции данных между клиниками (Фаза 4, мультитенант).

Без этих тестов фаза не закрыта. Каждый тест проверяет ОДИН незыблемый инвариант
мультитенантности — что данные клиники А никогда не утекают в контекст клиники Б
и наоборот. Всё на MockProvider, полностью офлайн (без ключей и сети).

Пять проверяемых пунктов (см. также management-команду test_multitenant_flow):
  1. Маршрутизация: входящее на инстанс/номер А попадает в контекст А, на Б — в Б;
     неизвестный номер не создаёт записей и не падает.
  2. Системный промпт А НЕ содержит услуг/цен/FAQ клиники Б (проверка строкой).
  3. История диалога: один пациентский номер в А и в Б = две независимые беседы;
     история А не возвращает сообщения Б.
  4. Заявки: booking клиники А не виден в выборке клиники Б; уведомление ушло
     только менеджеру А.
  5. Прямой запрос «дай все сообщения» с фильтром clinic_id=А не отдаёт строк Б.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from bookings.models import BookingRequest
from bookings.tasks import notify_manager
from clinics.models import Clinic
from messaging.models import Conversation, Message
from messaging.services import build_messages
from messaging.services.prompt import build_system_prompt
from messaging.services.conversation import get_history
from providers.ai.mock import MockAIProvider
from providers.whatsapp.mock import MockWhatsAppProvider

# Один и тот же пациент пишет в обе клиники — главный «провокатор» утечки.
CUSTOMER_PHONE = "77009998877"


# ---------------------------------------------------------------------------
# Fixtures: две клиники с ЗАВЕДОМО разными услугами / ценами / FAQ
# ---------------------------------------------------------------------------

@pytest.fixture
def clinic_a(db):
    return Clinic.objects.create(
        name="Клиника А",
        whatsapp_number="77001112233",
        instance_name="clinic-a",
        manager_whatsapp="77010000001",
        notifications_enabled=True,
        services_json=[{"name": "Чистка-А-уникальная", "price": "11 111 ₸"}],
        working_hours={"Пн-Пт": "09:00-18:00 (А)"},
        faq=[{"q": "Есть ли рассрочка в А?", "a": "Да, рассрочка-А Kaspi."}],
        tone="Тон клиники А.",
        address="Адрес-А, Алматы",
    )


@pytest.fixture
def clinic_b(db):
    return Clinic.objects.create(
        name="Клиника Б",
        whatsapp_number="77004445566",
        instance_name="clinic-b",
        manager_whatsapp="77020000002",
        notifications_enabled=True,
        services_json=[{"name": "Имплант-Б-уникальный", "price": "222 222 ₸"}],
        working_hours={"Сб-Вс": "10:00-16:00 (Б)"},
        faq=[{"q": "Есть ли наркоз в Б?", "a": "Да, седация-Б доступна."}],
        tone="Тон клиники Б.",
        address="Адрес-Б, Астана",
    )


def _run(mock_provider, **kwargs):
    """Прогнать handle_incoming_message на mock-провайдерах (офлайн)."""
    from messaging.tasks import handle_incoming_message

    with (
        patch("messaging.tasks.get_ai_provider", return_value=MockAIProvider()),
        patch(
            "messaging.tasks.get_whatsapp_provider_for_clinic",
            return_value=mock_provider,
        ),
    ):
        handle_incoming_message(**kwargs)


# ---------------------------------------------------------------------------
# Пункт 1. Маршрутизация: A→A, B→B, неизвестный — без записей и без падения
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_routing_message_to_a_lands_in_a(clinic_a, clinic_b):
    """Сообщение на инстанс/номер клиники А создаёт диалог и сообщения ТОЛЬКО в А."""
    provider = MockWhatsAppProvider()
    _run(
        provider,
        clinic_number=clinic_a.whatsapp_number,
        instance_name=clinic_a.instance_name,
        customer_phone=CUSTOMER_PHONE,
        text="сколько стоит чистка?",
        external_id="route-a-1",
    )

    assert Conversation.objects.filter(clinic=clinic_a, customer_phone=CUSTOMER_PHONE).exists()
    assert not Conversation.objects.filter(clinic=clinic_b).exists()
    assert Message.objects.filter(clinic=clinic_b).count() == 0


@pytest.mark.django_db
def test_routing_message_to_b_lands_in_b(clinic_a, clinic_b):
    """Зеркально: сообщение на клинику Б остаётся в контексте Б, не задевает А."""
    provider = MockWhatsAppProvider()
    _run(
        provider,
        clinic_number=clinic_b.whatsapp_number,
        instance_name=clinic_b.instance_name,
        customer_phone=CUSTOMER_PHONE,
        text="сколько стоит имплант?",
        external_id="route-b-1",
    )

    assert Conversation.objects.filter(clinic=clinic_b, customer_phone=CUSTOMER_PHONE).exists()
    assert not Conversation.objects.filter(clinic=clinic_a).exists()
    assert Message.objects.filter(clinic=clinic_a).count() == 0


@pytest.mark.django_db
def test_routing_unknown_number_creates_nothing(clinic_a, clinic_b):
    """Неизвестный номер/инстанс: ничего не создаём, ничего не шлём, не падаем."""
    provider = MockWhatsAppProvider()
    _run(
        provider,
        clinic_number="79990000000",
        instance_name="totally-unknown",
        customer_phone=CUSTOMER_PHONE,
        text="привет",
        external_id="route-unknown-1",
    )

    assert Conversation.objects.count() == 0
    assert Message.objects.count() == 0
    assert provider.sent == []


# ---------------------------------------------------------------------------
# Пункт 2. Системный промпт А не содержит услуг/цен/FAQ клиники Б
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_system_prompt_a_excludes_b_data(clinic_a, clinic_b):
    """Собранный промпт клиники А не содержит ни одной строки данных клиники Б."""
    prompt_a = build_system_prompt(clinic_a)

    # Свои данные — на месте.
    assert "Чистка-А-уникальная" in prompt_a
    assert "11 111 ₸" in prompt_a
    assert "рассрочка-А" in prompt_a
    assert clinic_a.name in prompt_a

    # Данные клиники Б — НИ ОДНОЙ строки.
    for leak in (
        "Имплант-Б-уникальный",
        "222 222 ₸",
        "седация-Б",
        "наркоз",
        clinic_b.name,
        "Адрес-Б",
    ):
        assert leak not in prompt_a, f"Утечка данных клиники Б в промпт А: {leak!r}"


@pytest.mark.django_db
def test_system_prompt_b_excludes_a_data(clinic_a, clinic_b):
    """Зеркально: промпт клиники Б не содержит услуг/цен/FAQ клиники А."""
    prompt_b = build_system_prompt(clinic_b)

    assert "Имплант-Б-уникальный" in prompt_b
    assert "222 222 ₸" in prompt_b

    for leak in (
        "Чистка-А-уникальная",
        "11 111 ₸",
        "рассрочка-А",
        clinic_a.name,
        "Адрес-А",
    ):
        assert leak not in prompt_b, f"Утечка данных клиники А в промпт Б: {leak!r}"


# ---------------------------------------------------------------------------
# Пункт 3. История диалога: один номер в A и B = две независимые беседы
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_history_two_clinics_two_independent_conversations(clinic_a, clinic_b):
    """Один пациентский номер, написавший в А и в Б, даёт две раздельные истории."""
    provider = MockWhatsAppProvider()
    _run(
        provider,
        clinic_number=clinic_a.whatsapp_number,
        instance_name=clinic_a.instance_name,
        customer_phone=CUSTOMER_PHONE,
        text="вопрос в клинику А про чистку",
        external_id="hist-a-1",
    )
    _run(
        provider,
        clinic_number=clinic_b.whatsapp_number,
        instance_name=clinic_b.instance_name,
        customer_phone=CUSTOMER_PHONE,
        text="вопрос в клинику Б про имплант",
        external_id="hist-b-1",
    )

    conv_a = Conversation.objects.get(clinic=clinic_a, customer_phone=CUSTOMER_PHONE)
    conv_b = Conversation.objects.get(clinic=clinic_b, customer_phone=CUSTOMER_PHONE)
    assert conv_a.pk != conv_b.pk

    # История клиники А не содержит реплик, отправленных в клинику Б.
    history_a = get_history(conv_a)
    contents_a = [m["content"] for m in history_a]
    assert any("клинику А" in c for c in contents_a)
    assert all("клинику Б" not in c for c in contents_a), "История Б утекла в А"

    # И наоборот.
    history_b = get_history(conv_b)
    contents_b = [m["content"] for m in history_b]
    assert any("клинику Б" in c for c in contents_b)
    assert all("клинику А" not in c for c in contents_b), "История А утекла в Б"

    # build_messages для А не тянет сообщения Б в контекст модели.
    messages_a = build_messages(clinic_a, conv_a, "новый вопрос")
    joined_a = "\n".join(m["content"] for m in messages_a)
    assert "клинику Б" not in joined_a
    assert "Имплант-Б-уникальный" not in joined_a  # и услуг Б в промпте нет


# ---------------------------------------------------------------------------
# Пункт 4. Заявки: booking А не виден в выборке Б; уведомлён только менеджер А
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_booking_of_a_not_visible_in_b_queryset(clinic_a, clinic_b):
    """Заявка клиники А не попадает в выборку BookingRequest по клинике Б."""
    conv_a = Conversation.objects.create(clinic=clinic_a, customer_phone=CUSTOMER_PHONE)
    booking_a = BookingRequest.objects.create(
        clinic=clinic_a,
        conversation=conv_a,
        customer_phone=CUSTOMER_PHONE,
        service="Чистка-А-уникальная",
        status=BookingRequest.Status.NEW,
    )

    # Выборка «заявки клиники Б» не содержит заявку А.
    qs_b = BookingRequest.objects.filter(clinic=clinic_b)
    assert booking_a not in qs_b
    assert qs_b.count() == 0

    # Выборка клиники А содержит ровно её заявку.
    qs_a = BookingRequest.objects.filter(clinic=clinic_a)
    assert list(qs_a) == [booking_a]


@pytest.mark.django_db
def test_booking_notification_goes_only_to_clinic_a_manager(clinic_a, clinic_b):
    """notify_manager уведомляет менеджера А и не трогает провайдер/менеджера Б."""
    conv_a = Conversation.objects.create(clinic=clinic_a, customer_phone=CUSTOMER_PHONE)
    booking_a = BookingRequest.objects.create(
        clinic=clinic_a,
        conversation=conv_a,
        customer_phone=CUSTOMER_PHONE,
        service="Чистка-А-уникальная",
        preferred_date_raw="завтра",
        preferred_time_raw="в 14",
        status=BookingRequest.Status.NEW,
    )

    provider_a = MockWhatsAppProvider()
    provider_b = MockWhatsAppProvider()

    def _dispatch(clinic):
        return provider_a if clinic.id == clinic_a.id else provider_b

    with patch("bookings.tasks.get_whatsapp_provider_for_clinic", side_effect=_dispatch):
        notify_manager.apply(args=[booking_a.id])

    # Ровно одно уведомление — менеджеру клиники А.
    assert len(provider_a.sent) == 1
    assert provider_a.sent[0]["to"] == clinic_a.manager_whatsapp
    # Менеджер Б не получил ничего; его номер нигде не фигурирует.
    assert provider_b.sent == []
    assert all(m["to"] != clinic_b.manager_whatsapp for m in provider_a.sent)


# ---------------------------------------------------------------------------
# Пункт 5. Прямой запрос с фильтром clinic_id=А не отдаёт ни строки Б
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_direct_message_query_by_clinic_excludes_other(clinic_a, clinic_b):
    """«Дай все сообщения» с фильтром clinic_id=А не возвращает ни одной строки Б."""
    provider = MockWhatsAppProvider()
    _run(
        provider,
        clinic_number=clinic_a.whatsapp_number,
        instance_name=clinic_a.instance_name,
        customer_phone=CUSTOMER_PHONE,
        text="сообщение в А",
        external_id="q-a-1",
    )
    _run(
        provider,
        clinic_number=clinic_b.whatsapp_number,
        instance_name=clinic_b.instance_name,
        customer_phone=CUSTOMER_PHONE,
        text="сообщение в Б",
        external_id="q-b-1",
    )

    # Прямой «дамп» сообщений клиники А.
    msgs_a = Message.objects.filter(clinic=clinic_a)
    assert msgs_a.count() > 0
    # Ни одна строка не принадлежит клинике Б ни по прямому FK, ни через диалог.
    assert all(m.clinic_id == clinic_a.id for m in msgs_a)
    assert all(m.conversation.clinic_id == clinic_a.id for m in msgs_a)

    # Пересечение выборок А и Б по сообщениям — пусто.
    ids_a = set(Message.objects.filter(clinic=clinic_a).values_list("id", flat=True))
    ids_b = set(Message.objects.filter(clinic=clinic_b).values_list("id", flat=True))
    assert ids_a and ids_b
    assert ids_a.isdisjoint(ids_b)
