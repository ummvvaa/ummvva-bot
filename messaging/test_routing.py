"""
Тесты мультитенант-маршрутизации и изоляции (Фаза 4, Промпт #8.2).

На MockProvider, офлайн. Проверяем, что входящее обрабатывается СТРОГО в
контексте клиники, определённой по тому, КУДА оно пришло:
- маршрутизация по instance_name приоритетна над номером-получателем;
- запасной ключ — whatsapp_number, если инстанс не дал клинику;
- клиника не найдена / неактивна → НЕ отвечаем, НЕ заводим диалог, не падаем;
- один номер клиента в двух клиниках = две независимые беседы (изоляция).
"""
from unittest.mock import patch

import pytest

from clinics.models import Clinic
from messaging.models import Conversation, Message
from messaging.webhook_parser import parse_evolution_payload
from providers.ai.mock import MockAIProvider
from providers.whatsapp.mock import MockWhatsAppProvider

CUSTOMER_PHONE = "77009998877"


def _run(mock_provider, **kwargs):
    """Прогнать handle_incoming_message на mock-провайдерах."""
    from messaging.tasks import handle_incoming_message

    with (
        patch("messaging.tasks.get_ai_provider", return_value=MockAIProvider()),
        patch("messaging.tasks.get_whatsapp_provider_for_clinic", return_value=mock_provider),
    ):
        handle_incoming_message(customer_phone=CUSTOMER_PHONE, **kwargs)


@pytest.fixture
def clinic_a(db):
    return Clinic.objects.create(
        name="Клиника А",
        whatsapp_number="77001112233",
        instance_name="clinic-a",
        services_json=[{"name": "Чистка", "price": "10 000 ₸"}],
    )


@pytest.fixture
def clinic_b(db):
    return Clinic.objects.create(
        name="Клиника Б",
        whatsapp_number="77004445566",
        instance_name="clinic-b",
        services_json=[{"name": "Имплант", "price": "200 000 ₸"}],
    )


# --- Парсер ----------------------------------------------------------------

def test_parser_extracts_instance_name():
    payload = {
        "instance": "clinic-a",
        "sender": "77001112233@s.whatsapp.net",
        "data": {
            "key": {"remoteJid": f"{CUSTOMER_PHONE}@s.whatsapp.net", "fromMe": False, "id": "X1"},
            "message": {"conversation": "привет"},
            "messageType": "conversation",
        },
    }
    incoming = parse_evolution_payload(payload)
    assert incoming is not None
    assert incoming.instance_name == "clinic-a"
    assert incoming.clinic_number == "77001112233"


def test_parser_routes_by_instance_without_sender():
    """Инстанс есть, номера-получателя нет — всё равно маршрутизируемо."""
    payload = {
        "instance": "clinic-a",
        "data": {
            "key": {"remoteJid": f"{CUSTOMER_PHONE}@s.whatsapp.net", "fromMe": False, "id": "X2"},
            "message": {"conversation": "привет"},
            "messageType": "conversation",
        },
    }
    incoming = parse_evolution_payload(payload)
    assert incoming is not None
    assert incoming.instance_name == "clinic-a"
    assert incoming.clinic_number == ""


# --- Маршрутизация ---------------------------------------------------------

@pytest.mark.django_db
def test_routes_by_instance_name(clinic_a):
    """instance_name определяет клинику даже без совпадения по номеру."""
    mock_provider = MockWhatsAppProvider()
    _run(
        mock_provider,
        clinic_number="",  # номер не передан — маршрут только по инстансу
        instance_name="clinic-a",
        text="сколько стоит чистка?",
        external_id="r1",
    )
    conv = Conversation.objects.get(clinic=clinic_a, customer_phone=CUSTOMER_PHONE)
    assert conv.messages.filter(role=Message.Role.ASSISTANT).exists()
    assert [m for m in mock_provider.sent if m["to"] == CUSTOMER_PHONE]


@pytest.mark.django_db
def test_instance_priority_over_number(clinic_a, clinic_b):
    """При расхождении инстанс важнее номера: пишем в клинику инстанса."""
    mock_provider = MockWhatsAppProvider()
    _run(
        mock_provider,
        clinic_number=clinic_b.whatsapp_number,  # номер от Б
        instance_name="clinic-a",               # инстанс от А — он и решает
        text="сколько стоит чистка?",
        external_id="r2",
    )
    assert Conversation.objects.filter(clinic=clinic_a, customer_phone=CUSTOMER_PHONE).exists()
    assert not Conversation.objects.filter(clinic=clinic_b, customer_phone=CUSTOMER_PHONE).exists()


@pytest.mark.django_db
def test_falls_back_to_number(clinic_a):
    """Инстанс пуст/неизвестен → маршрут по номеру-получателю."""
    mock_provider = MockWhatsAppProvider()
    _run(
        mock_provider,
        clinic_number=clinic_a.whatsapp_number,
        instance_name="unknown-instance",
        text="сколько стоит чистка?",
        external_id="r3",
    )
    assert Conversation.objects.filter(clinic=clinic_a, customer_phone=CUSTOMER_PHONE).exists()


# --- Клиника не найдена / неактивна ----------------------------------------

@pytest.mark.django_db
def test_unknown_clinic_is_dropped(db):
    """Ни инстанс, ни номер не совпали → ничего не делаем (не падаем, не отвечаем)."""
    mock_provider = MockWhatsAppProvider()
    _run(
        mock_provider,
        clinic_number="79990000000",
        instance_name="nope",
        text="привет",
        external_id="r4",
    )
    assert Conversation.objects.count() == 0
    assert mock_provider.sent == []


@pytest.mark.django_db
def test_inactive_clinic_is_dropped(clinic_a):
    """Клиника есть, но is_active=False → не отвечаем, диалог не заводим."""
    clinic_a.is_active = False
    clinic_a.save(update_fields=["is_active"])
    mock_provider = MockWhatsAppProvider()
    _run(
        mock_provider,
        clinic_number=clinic_a.whatsapp_number,
        instance_name=clinic_a.instance_name,
        text="привет",
        external_id="r5",
    )
    assert Conversation.objects.count() == 0
    assert mock_provider.sent == []


# --- Изоляция --------------------------------------------------------------

@pytest.mark.django_db
def test_same_customer_two_clinics_isolated(clinic_a, clinic_b):
    """Один номер клиента, две клиники → две независимые беседы."""
    mock_provider = MockWhatsAppProvider()
    _run(
        mock_provider,
        clinic_number=clinic_a.whatsapp_number,
        instance_name=clinic_a.instance_name,
        text="сколько стоит чистка?",
        external_id="iso-a",
    )
    _run(
        mock_provider,
        clinic_number=clinic_b.whatsapp_number,
        instance_name=clinic_b.instance_name,
        text="сколько стоит имплант?",
        external_id="iso-b",
    )

    conv_a = Conversation.objects.get(clinic=clinic_a, customer_phone=CUSTOMER_PHONE)
    conv_b = Conversation.objects.get(clinic=clinic_b, customer_phone=CUSTOMER_PHONE)
    assert conv_a.pk != conv_b.pk

    # Сообщения каждой беседы привязаны к своей клинике — без перекрёстной утечки.
    assert all(m.clinic_id == clinic_a.id for m in conv_a.messages.all())
    assert all(m.clinic_id == clinic_b.id for m in conv_b.messages.all())
    assert Message.objects.filter(clinic=clinic_a).count() == conv_a.messages.count()
