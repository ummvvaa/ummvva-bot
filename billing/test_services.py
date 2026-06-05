"""
Тесты сервисного слоя подписки (Фаза 5, Промпт #2). На mock, без сети.

Покрываем ВСЕ ветки гейта и переходов. Время гоняем фиксированными часами:
монипатчим `django.utils.timezone.now` (freezegun в окружении нет, поэтому
управляемый clock — единый источник «сейчас» для сервисов, сигнала и auto_now).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal

import pytest
from django.conf import settings

from billing import services
from billing.models import Plan, Subscription, UsageCounter
from clinics.models import Clinic


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
    # Один источник времени для всех (services, signals, auto_now/auto_now_add).
    monkeypatch.setattr("django.utils.timezone.now", c)
    return c


@pytest.fixture
def plan(db):
    return Plan.objects.create(
        code="t",
        name="Test",
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
        whatsapp_number=f"7700999{_counter['n']:04d}",
    )


def reload_clinic(clinic: Clinic) -> Clinic:
    """Свежая клиника из БД — сбрасывает кеш reverse-OneToOne (subscription)."""
    return Clinic.objects.get(pk=clinic.pk)


# --------------------------------------------------------------------------- #
# is_clinic_serviceable                                                        #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_trial_not_expired_is_serviceable(clock):
    clinic = make_clinic()  # триал на TRIAL_DAYS от now
    assert services.is_clinic_serviceable(clinic) is True
    clock.advance(days=settings.TRIAL_DAYS - 1)
    assert services.is_clinic_serviceable(reload_clinic(clinic)) is True


@pytest.mark.django_db
def test_trial_expired_beyond_grace_not_serviceable(clock):
    clinic = make_clinic()
    # Триал кончился И грейс прошёл — даже если задача суспенда не отработала
    # (статус всё ещё trialing), гейт обязан вернуть False по сроку.
    clock.advance(days=settings.TRIAL_DAYS + settings.GRACE_DAYS + 1)
    sub = reload_clinic(clinic).subscription
    assert sub.status == Subscription.Status.TRIALING  # суспенд не запускали
    assert services.is_clinic_serviceable(reload_clinic(clinic)) is False


@pytest.mark.django_db
def test_active_within_period_is_serviceable(clock, plan):
    clinic = make_clinic()
    services.activate(clinic.subscription, plan=plan, period_days=30)
    clock.advance(days=10)
    assert services.is_clinic_serviceable(reload_clinic(clinic)) is True


@pytest.mark.django_db
def test_active_expired_but_within_grace_is_serviceable(clock, plan):
    clinic = make_clinic()
    services.activate(clinic.subscription, plan=plan, period_days=30)
    # Период (30 дней) кончился, но мы внутри грейса (GRACE_DAYS=3).
    clock.advance(days=31)
    assert services.is_clinic_serviceable(reload_clinic(clinic)) is True
    # А за пределами грейса — уже нет.
    clock.advance(days=settings.GRACE_DAYS)  # now = +34, deadline = +33
    assert services.is_clinic_serviceable(reload_clinic(clinic)) is False


@pytest.mark.django_db
def test_suspended_not_serviceable(clock, plan):
    clinic = make_clinic()
    services.activate(clinic.subscription, plan=plan, period_days=30)
    services.suspend(reload_clinic(clinic).subscription)
    # Период ещё в будущем, но статус suspended → не обслуживаем.
    assert services.is_clinic_serviceable(reload_clinic(clinic)) is False


@pytest.mark.django_db
def test_canceled_not_serviceable(clock, plan):
    clinic = make_clinic()
    services.activate(clinic.subscription, plan=plan, period_days=30)
    sub = services.cancel(reload_clinic(clinic).subscription)
    assert sub.canceled_at is not None
    assert services.is_clinic_serviceable(reload_clinic(clinic)) is False


@pytest.mark.django_db
def test_no_subscription_not_serviceable(clock):
    clinic = make_clinic()
    Subscription.objects.filter(clinic=clinic).delete()
    assert services.is_clinic_serviceable(reload_clinic(clinic)) is False


@pytest.mark.django_db
def test_inactive_clinic_not_serviceable(clock):
    clinic = make_clinic()  # валидный триал
    clinic.is_active = False
    clinic.save()
    assert services.is_clinic_serviceable(reload_clinic(clinic)) is False


# --------------------------------------------------------------------------- #
# start_trial                                                                  #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_start_trial_idempotent(clock):
    clinic = make_clinic()
    Subscription.objects.filter(clinic=clinic).delete()
    s1 = services.start_trial(reload_clinic(clinic))
    s2 = services.start_trial(reload_clinic(clinic))
    assert s1.pk == s2.pk
    assert Subscription.objects.filter(clinic=clinic).count() == 1
    assert s1.status == Subscription.Status.TRIALING


# --------------------------------------------------------------------------- #
# activate / renew                                                             #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_activate_from_suspended_restores(clock, plan):
    clinic = make_clinic()
    services.activate(clinic.subscription, plan=plan, period_days=30)
    services.suspend(reload_clinic(clinic).subscription)
    assert services.is_clinic_serviceable(reload_clinic(clinic)) is False

    sub = services.activate(reload_clinic(clinic).subscription, plan=plan)
    assert sub.status == Subscription.Status.ACTIVE
    assert sub.canceled_at is None
    # period_days по умолчанию из плана (30).
    assert sub.current_period_end == sub.current_period_start + timedelta(days=30)
    assert services.is_clinic_serviceable(reload_clinic(clinic)) is True


@pytest.mark.django_db
def test_renew_continuous_moves_boundaries(clock, plan):
    clinic = make_clinic()
    sub = services.activate(clinic.subscription, plan=plan, period_days=30)
    old_end = sub.current_period_end

    clock.advance(days=5)  # ещё в периоде, не просрочен
    sub = services.renew(reload_clinic(clinic).subscription)
    # Непрерывное продление: новый старт = старый конец, конец += period_days.
    assert sub.current_period_start == old_end
    assert sub.current_period_end == old_end + timedelta(days=30)
    assert sub.status == Subscription.Status.ACTIVE


@pytest.mark.django_db
def test_renew_after_expiry_starts_from_now(clock, plan):
    clinic = make_clinic()
    services.activate(clinic.subscription, plan=plan, period_days=30)

    clock.advance(days=100)  # давно просрочен
    sub = services.renew(reload_clinic(clinic).subscription)
    # Просрочен → новый старт = now, конец = now + period_days.
    assert sub.current_period_start == clock.now
    assert sub.current_period_end == clock.now + timedelta(days=30)
    assert sub.status == Subscription.Status.ACTIVE


@pytest.mark.django_db
def test_renew_without_plan_raises(clock):
    clinic = make_clinic()  # триал без plan
    with pytest.raises(ValueError):
        services.renew(clinic.subscription)


# --------------------------------------------------------------------------- #
# mark_past_due                                                                #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_mark_past_due_transitions(clock, plan):
    clinic = make_clinic()
    services.activate(clinic.subscription, plan=plan, period_days=30)
    sub = services.mark_past_due(reload_clinic(clinic).subscription)
    assert sub.status == Subscription.Status.PAST_DUE


# --------------------------------------------------------------------------- #
# get_or_create_usage                                                          #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_usage_created_once_per_period(clock):
    clinic = make_clinic()
    u1 = services.get_or_create_usage(clinic)
    u1.messages_in = 5
    u1.save()
    u2 = services.get_or_create_usage(clinic)
    assert u1.pk == u2.pk
    assert u2.messages_in == 5
    assert UsageCounter.objects.filter(clinic=clinic).count() == 1
    # Период счётчика = границы периода подписки, не календарный месяц.
    sub = reload_clinic(clinic).subscription
    assert u2.period_start == sub.current_period_start


# --------------------------------------------------------------------------- #
# is_over_limit                                                                #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_is_over_limit_triggers_on_messages_in(clock, plan):
    clinic = make_clinic()
    services.activate(clinic.subscription, plan=plan, period_days=30)  # limit 1000

    assert services.is_over_limit(reload_clinic(clinic)) is False

    usage = services.get_or_create_usage(reload_clinic(clinic))
    usage.messages_in = 1000  # ровно лимит — ещё не превышен
    usage.save()
    assert services.is_over_limit(reload_clinic(clinic)) is False

    usage.messages_in = 1001  # превышен
    usage.save()
    assert services.is_over_limit(reload_clinic(clinic)) is True


@pytest.mark.django_db
def test_is_over_limit_false_for_unlimited_plan(clock):
    unlimited = Plan.objects.create(
        code="pro_u", name="Pro", price_kzt=Decimal("30000.00"),
        period_days=30, message_limit=None,
    )
    clinic = make_clinic()
    services.activate(clinic.subscription, plan=unlimited, period_days=30)
    usage = services.get_or_create_usage(reload_clinic(clinic))
    usage.messages_in = 999999
    usage.save()
    assert services.is_over_limit(reload_clinic(clinic)) is False


@pytest.mark.django_db
def test_is_over_limit_false_without_subscription(clock):
    clinic = make_clinic()
    Subscription.objects.filter(clinic=clinic).delete()
    assert services.is_over_limit(reload_clinic(clinic)) is False
