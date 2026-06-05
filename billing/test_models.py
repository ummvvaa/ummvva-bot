"""
Тесты биллинга (Фаза 5). На mock, без сети.

Проверяем:
- автотриал: при СОЗДАНИИ клиники сигнал заводит подписку trialing на TRIAL_DAYS;
- повторный save клиники НЕ плодит подписки (get_or_create);
- деньги хранятся как Decimal (без float);
- тарифы-плейсхолдеры из data-миграции существуют (start с лимитом, pro безлимит);
- уникальные ограничения UsageCounter и BillingEventLog работают.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone

from billing.models import (
    BillingEventLog,
    Payment,
    Plan,
    Subscription,
    UsageCounter,
)
from clinics.models import Clinic


@pytest.mark.django_db
def test_creating_clinic_creates_trial_subscription():
    clinic = Clinic.objects.create(name="Новая клиника", whatsapp_number="77001230001")

    sub = Subscription.objects.get(clinic=clinic)
    assert sub.status == Subscription.Status.TRIALING
    assert sub.trial_end is not None
    assert sub.current_period_start is not None
    assert sub.current_period_end == sub.trial_end
    # trial_end ≈ now + TRIAL_DAYS (с запасом на время выполнения теста).
    expected = timezone.now() + timedelta(days=settings.TRIAL_DAYS)
    assert abs((sub.trial_end - expected).total_seconds()) < 120


@pytest.mark.django_db
def test_resaving_clinic_does_not_duplicate_subscription():
    clinic = Clinic.objects.create(name="Клиника", whatsapp_number="77001230002")
    clinic.name = "Клиника (переименована)"
    clinic.save()
    clinic.save()

    assert Subscription.objects.filter(clinic=clinic).count() == 1


@pytest.mark.django_db
def test_money_is_decimal():
    plan = Plan.objects.create(code="x", name="X", price_kzt=Decimal("12345.67"))
    fetched = Plan.objects.get(pk=plan.pk)
    assert isinstance(fetched.price_kzt, Decimal)
    assert fetched.price_kzt == Decimal("12345.67")


@pytest.mark.django_db
def test_seed_plans_exist():
    """Тарифы-плейсхолдеры созданы data-миграцией 0002."""
    start = Plan.objects.get(code="start")
    pro = Plan.objects.get(code="pro")
    assert start.message_limit == 1000
    assert pro.message_limit is None  # безлимит
    assert isinstance(start.price_kzt, Decimal)


@pytest.mark.django_db
def test_payment_defaults():
    clinic = Clinic.objects.create(name="К", whatsapp_number="77001230003")
    payment = Payment.objects.create(clinic=clinic, amount_kzt=Decimal("15000.00"))
    assert payment.status == Payment.Status.PENDING
    assert payment.provider == "manual"


@pytest.mark.django_db
def test_usage_counter_unique_per_period():
    clinic = Clinic.objects.create(name="К", whatsapp_number="77001230004")
    now = timezone.now()
    end = now + timedelta(days=30)
    UsageCounter.objects.create(clinic=clinic, period_start=now, period_end=end)
    with pytest.raises(IntegrityError):
        UsageCounter.objects.create(clinic=clinic, period_start=now, period_end=end)


@pytest.mark.django_db
def test_billing_event_log_unique():
    clinic = Clinic.objects.create(name="К", whatsapp_number="77001230005")
    sub = Subscription.objects.get(clinic=clinic)
    BillingEventLog.objects.create(
        subscription=sub,
        period_key="2026-06",
        event_type=BillingEventLog.EventType.REMINDER_3D,
    )
    with pytest.raises(IntegrityError):
        BillingEventLog.objects.create(
            subscription=sub,
            period_key="2026-06",
            event_type=BillingEventLog.EventType.REMINDER_3D,
        )
