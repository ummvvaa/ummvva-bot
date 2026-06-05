"""
Тесты платёжного провайдера (Фаза 5, Промпт #4). Manual-провайдер, офлайн.

Покрываем контракт ManualBillingProvider:
  • create_payment → Payment(pending) на верный период и сумму;
  • confirm_payment → paid + подписка active/продлена на нужные даты;
  • повторный confirm того же Payment НЕ двигает период второй раз (идемпотентность).

Время гоняем фиксированными часами (как в test_services): монипатчим
django.utils.timezone.now (freezegun в окружении нет).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal

import pytest

from billing.models import Payment, Plan, Subscription
from clinics.models import Clinic
from providers.billing.factory import get_billing_provider
from providers.billing.kaspi import KaspiBillingProvider
from providers.billing.manual import ManualBillingProvider


class Clock:
    """Управляемые «часы»: вызов возвращает текущее зафиксированное время."""

    def __init__(self, dt: datetime):
        self.now = dt

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now = self.now + timedelta(**kwargs)


@pytest.fixture
def clock(monkeypatch):
    c = Clock(datetime(2026, 6, 5, 12, 0, tzinfo=dt_tz.utc))
    # Единый источник «сейчас» для провайдера, сервисов, сигнала и auto_now.
    monkeypatch.setattr("django.utils.timezone.now", c)
    return c


@pytest.fixture
def plan(db):
    return Plan.objects.create(
        code="prov_test",
        name="Старт",
        price_kzt=Decimal("15000.00"),
        period_days=30,
        message_limit=1000,
    )


_counter = {"n": 0}


def make_clinic() -> Clinic:
    """Клиника с уникальным номером (триал заводит сигнал автоматически)."""
    _counter["n"] += 1
    return Clinic.objects.create(
        name=f"Клиника {_counter['n']}",
        whatsapp_number=f"7701000{_counter['n']:04d}",
    )


def reload_sub(subscription: Subscription) -> Subscription:
    """Свежая подписка из БД."""
    return Subscription.objects.get(pk=subscription.pk)


# --------------------------------------------------------------------------- #
# Фабрика                                                                      #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_factory_default_is_manual(settings):
    settings.BILLING_PROVIDER = "manual"
    get_billing_provider.cache_clear()
    assert isinstance(get_billing_provider(), ManualBillingProvider)
    get_billing_provider.cache_clear()


@pytest.mark.django_db
def test_factory_kaspi_is_wired_but_stub(settings, plan):
    settings.BILLING_PROVIDER = "kaspi"
    get_billing_provider.cache_clear()
    provider = get_billing_provider()
    assert isinstance(provider, KaspiBillingProvider)
    # Класс существует и подключён, но методы — застаб.
    with pytest.raises(NotImplementedError):
        provider.handle_webhook({})
    get_billing_provider.cache_clear()


# --------------------------------------------------------------------------- #
# create_payment                                                               #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_create_payment_pending_amount_and_period(clock, plan):
    clinic = make_clinic()
    sub = reload_sub(clinic.subscription)

    payment = ManualBillingProvider().create_payment(sub, plan)

    assert payment.status == Payment.Status.PENDING
    assert payment.provider == "manual"
    assert payment.amount_kzt == plan.price_kzt
    assert payment.clinic_id == clinic.pk
    assert payment.subscription_id == sub.pk
    assert payment.plan_id == plan.pk
    assert payment.paid_at is None
    # Период рассчитан от plan.period_days, начиная с now.
    assert payment.period_start == clock.now
    assert payment.period_end == clock.now + timedelta(days=plan.period_days)


# --------------------------------------------------------------------------- #
# confirm_payment                                                              #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_confirm_payment_activates_from_trial(clock, plan):
    clinic = make_clinic()  # триал
    sub = reload_sub(clinic.subscription)
    assert sub.status == Subscription.Status.TRIALING

    provider = ManualBillingProvider()
    payment = provider.create_payment(sub, plan)
    provider.confirm_payment(payment)

    payment.refresh_from_db()
    assert payment.status == Payment.Status.PAID
    assert payment.paid_at == clock.now

    sub = reload_sub(sub)
    assert sub.status == Subscription.Status.ACTIVE
    assert sub.plan_id == plan.pk
    # Триал → activate: период от now на plan.period_days.
    assert sub.current_period_start == clock.now
    assert sub.current_period_end == clock.now + timedelta(days=plan.period_days)


@pytest.mark.django_db
def test_confirm_payment_renews_active_from_period_end(clock, plan):
    clinic = make_clinic()
    sub = reload_sub(clinic.subscription)

    provider = ManualBillingProvider()
    # Первая оплата: триал → active.
    provider.confirm_payment(provider.create_payment(sub, plan))
    sub = reload_sub(sub)
    first_end = sub.current_period_end
    assert sub.status == Subscription.Status.ACTIVE

    # Вторая оплата спустя время, но в пределах периода → renew от старого конца.
    clock.advance(days=10)
    provider.confirm_payment(provider.create_payment(sub, plan))

    sub = reload_sub(sub)
    assert sub.status == Subscription.Status.ACTIVE
    # Непрерывное продление: новый старт = старый конец, не «съедает» дни.
    assert sub.current_period_start == first_end
    assert sub.current_period_end == first_end + timedelta(days=plan.period_days)


@pytest.mark.django_db
def test_confirm_payment_idempotent(clock, plan):
    clinic = make_clinic()
    sub = reload_sub(clinic.subscription)

    provider = ManualBillingProvider()
    payment = provider.create_payment(sub, plan)
    provider.confirm_payment(payment)

    sub = reload_sub(sub)
    end_after_first = sub.current_period_end
    paid_at_first = Payment.objects.get(pk=payment.pk).paid_at

    # Повторный confirm того же Payment (даже спустя время) НЕ двигает период.
    clock.advance(days=5)
    provider.confirm_payment(payment)
    # И даже свежий из БД объект — тоже no-op (статус уже paid).
    provider.confirm_payment(Payment.objects.get(pk=payment.pk))

    sub = reload_sub(sub)
    assert sub.current_period_end == end_after_first
    assert Payment.objects.get(pk=payment.pk).paid_at == paid_at_first


@pytest.mark.django_db
def test_manual_handle_webhook_is_noop(plan):
    assert ManualBillingProvider().handle_webhook({"any": "payload"}) is None
