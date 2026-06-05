"""
Тесты гейта подписки в пайплайне обработки входящих (Фаза 5, Промпт #3).

На mock-провайдерах, офлайн. Проверяем вставку МЕЖДУ «определили клинику» и
«дёрнули AI»:
  • оплаченная/триальная клиника → AI вызывается, счётчики растут, без задвоения
    при ретрае Celery-задачи (дедуп по external_id);
  • suspended-клиника → Groq НЕ вызывается (мок-провайдер не дёрнут), сообщения/
    заявки не создаются, задача не падает;
  • уведомление «сервис недоступен» — с тротлингом (два сообщения подряд → один раз);
  • мягкий лимит сообщений → алерт фиксируется ровно один раз за период, бот работает.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from billing import services
from billing.models import BillingEventLog, Plan, Subscription, UsageCounter
from bookings.models import BookingRequest
from clinics.models import Clinic
from messaging.models import Conversation, Message
from providers.whatsapp.mock import MockWhatsAppProvider

CUSTOMER_PHONE = "77009998877"


@pytest.fixture
def clinic(db):
    # Создание клиники триггерит сигнал автотриала → подписка trialing (serviceable).
    return Clinic.objects.create(
        name="Тест-Клиника",
        whatsapp_number="77001112233",
        instance_name="clinic-test",
        services_json=[{"name": "Чистка", "price": "10 000 ₸"}],
    )


def _run(clinic_number="77001112233", *, ai=None, wa=None, **kwargs):
    """Прогнать handle_incoming_message с подменёнными провайдерами.

    Возвращает (ai_mock, wa_mock), чтобы проверять вызовы/отправленное.
    """
    from messaging.tasks import handle_incoming_message

    ai = ai if ai is not None else MagicMock()
    ai.generate.return_value = "Ответ бота"
    ai.transcribe.return_value = "распознанный текст"
    wa = wa if wa is not None else MockWhatsAppProvider()

    with (
        patch("messaging.tasks.get_ai_provider", return_value=ai),
        patch("messaging.tasks.get_whatsapp_provider_for_clinic", return_value=wa),
    ):
        handle_incoming_message(
            clinic_number=clinic_number, customer_phone=CUSTOMER_PHONE, **kwargs
        )
    return ai, wa


# --------------------------------------------------------------------------- #
# Оплаченная/триальная клиника                                                 #
# --------------------------------------------------------------------------- #
def test_serviceable_clinic_calls_ai_and_grows_counters(clinic):
    assert services.is_clinic_serviceable(clinic) is True

    ai, wa = _run(text="сколько стоит чистка?", external_id="msg-1")

    # AI вызван, ответ пациенту ушёл.
    ai.generate.assert_called_once()
    assert any(s["to"] == CUSTOMER_PHONE for s in wa.sent)

    usage = services.get_or_create_usage(clinic)
    assert usage.messages_in == 1
    assert usage.ai_calls == 1
    assert usage.messages_out == 1


def test_retry_does_not_double_count(clinic):
    # Первый прогон.
    ai1, _ = _run(text="сколько стоит чистка?", external_id="dup-1")
    ai1.generate.assert_called_once()

    # Ретрай той же задачи (тот же external_id) — дедуп должен сработать.
    ai2, _ = _run(text="сколько стоит чистка?", external_id="dup-1")
    ai2.generate.assert_not_called()  # до AI не дошли — это дубль

    usage = services.get_or_create_usage(clinic)
    assert usage.messages_in == 1
    assert usage.ai_calls == 1
    assert usage.messages_out == 1
    # Ровно одно входящее и один ответ сохранены.
    assert Message.objects.filter(clinic=clinic, role=Message.Role.USER).count() == 1
    assert Message.objects.filter(clinic=clinic, role=Message.Role.ASSISTANT).count() == 1


# --------------------------------------------------------------------------- #
# Suspended-клиника                                                            #
# --------------------------------------------------------------------------- #
def _suspend(clinic):
    services.suspend(clinic.subscription)


def test_suspended_clinic_does_not_call_ai(clinic):
    _suspend(clinic)
    assert services.is_clinic_serviceable(clinic) is False

    ai, wa = _run(text="хочу записаться на чистку завтра в 15", external_id="susp-1")

    # Главное правило: Groq не дёргаем вообще.
    ai.generate.assert_not_called()
    ai.transcribe.assert_not_called()

    # Сообщения и заявки не создаются (бот не обслуживает).
    assert Message.objects.filter(clinic=clinic).count() == 0
    assert BookingRequest.objects.filter(clinic=clinic).count() == 0
    # Счётчики не растут (не serviceable).
    assert not UsageCounter.objects.filter(clinic=clinic, messages_in__gt=0).exists()


def test_suspended_notice_is_throttled(clinic):
    _suspend(clinic)
    wa = MockWhatsAppProvider()

    # Два сообщения подряд от одного пациента.
    _run(text="здравствуйте", external_id="n-1", wa=wa)
    _run(text="вы работаете?", external_id="n-2", wa=wa)

    # Уведомление «сервис недоступен» ушло РОВНО один раз (тротлинг).
    notices = [s for s in wa.sent if "недоступен" in s["text"].lower()]
    assert len(notices) == 1
    # Отметка о последней отправке проставлена на диалоге.
    conv = Conversation.objects.get(clinic=clinic, customer_phone=CUSTOMER_PHONE)
    assert conv.suspended_notice_at is not None


def test_suspended_notice_can_be_disabled(clinic, settings):
    _suspend(clinic)
    settings.SEND_SUSPENDED_NOTICE = False
    _, wa = _run(text="здравствуйте", external_id="off-1")
    assert wa.sent == []  # ничего не отправили


# --------------------------------------------------------------------------- #
# Мягкий лимит сообщений                                                       #
# --------------------------------------------------------------------------- #
def test_over_limit_alert_logged_once_without_disabling_bot(clinic):
    # Тариф с лимитом 1 входящее за период.
    plan = Plan.objects.create(
        code="lim", name="Лимит", price_kzt=Decimal("1.00"),
        period_days=30, message_limit=1,
    )
    sub = clinic.subscription
    sub.plan = plan
    sub.save(update_fields=["plan"])

    # Первое сообщение — ещё в пределах лимита (1 > 1 == False).
    ai1, _ = _run(text="вопрос 1", external_id="lim-1")
    ai1.generate.assert_called_once()  # бот работает
    assert not BillingEventLog.objects.filter(
        event_type=BillingEventLog.EventType.LIMIT_REACHED
    ).exists()

    # Второе — лимит превышен (2 > 1) → алерт фиксируется, бот НЕ отключается.
    ai2, _ = _run(text="вопрос 2", external_id="lim-2")
    ai2.generate.assert_called_once()  # бот по-прежнему отвечает
    assert BillingEventLog.objects.filter(
        subscription=sub, event_type=BillingEventLog.EventType.LIMIT_REACHED
    ).count() == 1

    # Третье — алерт повторно НЕ дублируется (один раз за период).
    _run(text="вопрос 3", external_id="lim-3")
    assert BillingEventLog.objects.filter(
        subscription=sub, event_type=BillingEventLog.EventType.LIMIT_REACHED
    ).count() == 1
