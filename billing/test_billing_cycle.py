"""
Тесты ежедневного billing-cycle (Фаза 5, Промпт #5). На mock-провайдере, офлайн.

Время гоняем управляемыми часами (монипатч `django.utils.timezone.now`) — freezegun
в окружении нет, как и в остальных billing-тестах (см. test_services.py).

Проверяем идемпотентность (за период каждое событие — ровно один раз):
  • T-3 и T-1 → по одному напоминанию; повторный прогон в тот же день не дублирует;
  • конец периода → past_due, бот по гейту ещё обслуживает (в пределах grace);
  • после grace → suspended ровно один раз; повторный прогон — без второго суспенда;
  • продление (renew) сбрасывает период → напоминания нового периода считаются заново;
  • превышение лимита → алерт владельцу один раз за период (или только лог, если пусто).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal

import pytest
from django.conf import settings

from billing import services
from billing.models import BillingEventLog, Plan, Subscription
from billing.tasks import run_billing_cycle
from clinics.models import Clinic
from providers.whatsapp.mock import MockWhatsAppProvider

MANAGER = "77009990000"
OWNER = "77000000001"


class Clock:
    """Управляемые «часы»: вызов возвращает зафиксированное «сейчас»."""

    def __init__(self, dt: datetime):
        self.now = dt

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now = self.now + timedelta(**kwargs)


@pytest.fixture
def clock(monkeypatch):
    c = Clock(datetime(2026, 6, 5, 9, 0, tzinfo=dt_tz.utc))
    monkeypatch.setattr("django.utils.timezone.now", c)
    return c


@pytest.fixture
def wa(monkeypatch):
    """Mock WhatsApp-провайдер, подменяющий фабрику внутри billing.tasks."""
    provider = MockWhatsAppProvider()
    monkeypatch.setattr(
        "billing.tasks.get_whatsapp_provider_for_clinic", lambda clinic: provider
    )
    return provider


@pytest.fixture
def plan(db):
    return Plan.objects.create(
        code="cycle_test",
        name="Цикл-тест",
        price_kzt=Decimal("15000"),
        period_days=30,
        message_limit=1000,
    )


def make_clinic(name="Клиника", number="77001112233", instance="cyc-test"):
    # Сигнал автотриала заведёт подписку trialing; период переопределяем set_sub.
    return Clinic.objects.create(
        name=name,
        whatsapp_number=number,
        instance_name=instance,
        manager_whatsapp=MANAGER,
        services_json=[{"name": "Чистка", "price": "10 000 ₸"}],
    )


def set_sub(clinic, plan, *, status, end):
    """Переопределить подписку клиники под нужный статус и конец периода."""
    sub = clinic.subscription
    sub.plan = plan
    sub.status = status
    sub.current_period_start = end - timedelta(days=plan.period_days)
    sub.current_period_end = end
    sub.save()
    return sub


def reload(clinic):
    """Свежий объект клиники (сбрасывает закешированную subscription)."""
    return Clinic.objects.get(pk=clinic.pk)


def manager_msgs(wa):
    return [s for s in wa.sent if s["to"] == MANAGER]


def suspend_msgs(wa):
    return [m for m in manager_msgs(wa) if "приостановлен" in m["text"]]


# --------------------------------------------------------------------------- #
# Напоминания об оплате T-3 / T-1                                              #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_reminder_t3_sends_once(clock, plan, wa):
    clinic = make_clinic()
    sub = set_sub(clinic, plan, status=Subscription.Status.ACTIVE, end=clock.now + timedelta(days=3))

    run_billing_cycle()
    msgs = manager_msgs(wa)
    assert len(msgs) == 1
    assert "через 3 дня" in msgs[0]["text"]
    assert BillingEventLog.objects.filter(
        subscription=sub, event_type=BillingEventLog.EventType.REMINDER_3D
    ).count() == 1
    # T-1 ещё не наступило.
    assert not BillingEventLog.objects.filter(
        subscription=sub, event_type=BillingEventLog.EventType.REMINDER_1D
    ).exists()

    # Повторный прогон в тот же день — без дубля.
    run_billing_cycle()
    assert len(manager_msgs(wa)) == 1


@pytest.mark.django_db
def test_reminder_t1_sends_once_after_t3(clock, plan, wa):
    clinic = make_clinic()
    sub = set_sub(clinic, plan, status=Subscription.Status.ACTIVE, end=clock.now + timedelta(days=3))

    run_billing_cycle()  # T-3
    assert len(manager_msgs(wa)) == 1

    clock.advance(days=2)  # now = end - 1 день → T-1
    run_billing_cycle()
    msgs = manager_msgs(wa)
    assert len(msgs) == 2
    assert "завтра" in msgs[1]["text"]
    assert BillingEventLog.objects.filter(
        subscription=sub, event_type=BillingEventLog.EventType.REMINDER_1D
    ).count() == 1

    # Повтор в тот же день — без второго напоминания.
    run_billing_cycle()
    assert len(manager_msgs(wa)) == 2


# --------------------------------------------------------------------------- #
# Просрочка → past_due (бот в грейсе ещё работает)                             #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_period_end_marks_past_due_and_bot_still_serves(clock, plan, wa):
    clinic = make_clinic()
    sub = set_sub(clinic, plan, status=Subscription.Status.ACTIVE, end=clock.now - timedelta(hours=1))

    run_billing_cycle()
    sub.refresh_from_db()
    assert sub.status == Subscription.Status.PAST_DUE
    # В пределах грейса гейт всё ещё пускает.
    assert services.is_clinic_serviceable(reload(clinic)) is True
    # Суспенда пока нет.
    assert not BillingEventLog.objects.filter(
        subscription=sub, event_type=BillingEventLog.EventType.EXPIRED_SUSPEND
    ).exists()
    assert suspend_msgs(wa) == []


# --------------------------------------------------------------------------- #
# Автосуспенд после грейса (ровно один раз)                                    #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_suspend_after_grace_exactly_once(clock, plan, wa):
    clinic = make_clinic()
    end = clock.now - timedelta(days=settings.GRACE_DAYS + 1)
    sub = set_sub(clinic, plan, status=Subscription.Status.PAST_DUE, end=end)

    run_billing_cycle()
    sub.refresh_from_db()
    assert sub.status == Subscription.Status.SUSPENDED
    assert len(suspend_msgs(wa)) == 1
    assert BillingEventLog.objects.filter(
        subscription=sub, event_type=BillingEventLog.EventType.EXPIRED_SUSPEND
    ).count() == 1

    # Повторный прогон — второй суспенд/уведомление НЕ шлём.
    run_billing_cycle()
    assert len(suspend_msgs(wa)) == 1
    assert services.is_clinic_serviceable(reload(clinic)) is False


@pytest.mark.django_db
def test_active_far_past_grace_suspends_in_one_run(clock, plan, wa):
    """Пропущенные дни beat: active за грейсом → past_due → suspended за один прогон."""
    clinic = make_clinic()
    end = clock.now - timedelta(days=settings.GRACE_DAYS + 5)
    sub = set_sub(clinic, plan, status=Subscription.Status.ACTIVE, end=end)

    run_billing_cycle()
    sub.refresh_from_db()
    assert sub.status == Subscription.Status.SUSPENDED
    assert len(suspend_msgs(wa)) == 1


# --------------------------------------------------------------------------- #
# Продление сбрасывает период → напоминания считаются заново                   #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_renew_resets_reminders_for_new_period(clock, plan, wa):
    clinic = make_clinic()
    sub = set_sub(clinic, plan, status=Subscription.Status.ACTIVE, end=clock.now + timedelta(days=3))

    run_billing_cycle()  # напоминание T-3 за текущий период
    assert len(manager_msgs(wa)) == 1

    # Оплата/продление: период сдвигается вперёд (новый period_key).
    services.renew(sub)
    sub.refresh_from_db()
    clock.now = sub.current_period_end - timedelta(days=3)  # T-3 нового периода

    run_billing_cycle()
    assert len(manager_msgs(wa)) == 2  # новое напоминание для нового периода
    assert BillingEventLog.objects.filter(
        subscription=sub, event_type=BillingEventLog.EventType.REMINDER_3D
    ).count() == 2  # по одному на каждый период


# --------------------------------------------------------------------------- #
# Мягкий лимит → уведомление владельца (раз за период)                         #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_over_limit_alerts_owner_once(clock, plan, wa, monkeypatch):
    monkeypatch.setattr(settings, "OWNER_WHATSAPP", OWNER)
    clinic = make_clinic()
    sub = set_sub(clinic, plan, status=Subscription.Status.ACTIVE, end=clock.now + timedelta(days=10))
    usage = services.get_or_create_usage(clinic)
    usage.messages_in = plan.message_limit + 5
    usage.save()

    run_billing_cycle()
    owner_msgs = [s for s in wa.sent if s["to"] == OWNER]
    assert len(owner_msgs) == 1
    assert BillingEventLog.objects.filter(
        subscription=sub, event_type=BillingEventLog.EventType.OWNER_LIMIT_ALERT
    ).count() == 1

    # Повтор — второй алерт владельцу не шлём.
    run_billing_cycle()
    assert len([s for s in wa.sent if s["to"] == OWNER]) == 1


@pytest.mark.django_db
def test_over_limit_without_owner_only_logs(clock, plan, wa, monkeypatch):
    monkeypatch.setattr(settings, "OWNER_WHATSAPP", "")
    clinic = make_clinic()
    sub = set_sub(clinic, plan, status=Subscription.Status.ACTIVE, end=clock.now + timedelta(days=10))
    usage = services.get_or_create_usage(clinic)
    usage.messages_in = plan.message_limit + 1
    usage.save()

    run_billing_cycle()
    # OWNER пуст → никому не слали, но событие за период зафиксировано (идемпотентность).
    assert wa.sent == []
    assert BillingEventLog.objects.filter(
        subscription=sub, event_type=BillingEventLog.EventType.OWNER_LIMIT_ALERT
    ).count() == 1
