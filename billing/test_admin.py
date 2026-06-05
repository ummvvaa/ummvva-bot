"""
Тесты admin-actions биллинга (Фаза 5, Промпт #6).

Проверяем:
  - SubscriptionAdmin.action_renew / action_activate_pro / action_to_trial / action_suspend;
  - PaymentAdmin.action_confirm_payment → вызывает ManualBillingProvider.confirm_payment;
  - get_queryset-скоупинг: ClinicUser видит только свою клинику, суперадмин — все.

Используем RequestFactory + AdminSite — без HTTP-стека, офлайн (MockProvider).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from billing.admin import PaymentAdmin, SubscriptionAdmin, UsageCounterAdmin
from billing.models import Payment, Plan, Subscription, UsageCounter
from clinics.models import Clinic, ClinicUser


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

def _req(factory, user):
    """POST-запрос с сессией и message-хранилищем (нужно для message_user)."""
    req = factory.post("/")
    req.user = user
    req.session = {}
    req._messages = FallbackStorage(req)
    return req


# --------------------------------------------------------------------------- #
# Fixtures                                                                      #
# --------------------------------------------------------------------------- #

@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def site():
    return AdminSite()


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser("admin", "admin@example.com", "pass")


@pytest.fixture
def plan_start(db):
    plan, _ = Plan.objects.get_or_create(
        code="start",
        defaults={
            "name": "Старт",
            "price_kzt": Decimal("15000.00"),
            "period_days": 30,
            "message_limit": 1000,
        },
    )
    return plan


@pytest.fixture
def plan_pro(db):
    plan, _ = Plan.objects.get_or_create(
        code="pro",
        defaults={
            "name": "Pro",
            "price_kzt": Decimal("30000.00"),
            "period_days": 30,
            "message_limit": None,
        },
    )
    return plan


@pytest.fixture
def clinic_a(db):
    return Clinic.objects.create(name="Клиника А", whatsapp_number="77099900001")


@pytest.fixture
def clinic_b(db):
    return Clinic.objects.create(name="Клиника Б", whatsapp_number="77099900002")


@pytest.fixture
def clinic_user(db, clinic_a):
    """Не-суперюзер, привязанный к clinic_a через ClinicUser."""
    user = User.objects.create_user("manager_a", password="pass")
    ClinicUser.objects.create(user=user, clinic=clinic_a)
    return user


# --------------------------------------------------------------------------- #
# SubscriptionAdmin actions                                                     #
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
def test_action_renew(plan_start, clinic_a, superuser, site, rf):
    """action_renew продлевает активную подписку на следующий период."""
    sub = Subscription.objects.get(clinic=clinic_a)
    # Активируем сначала, чтобы можно было продлить (renew требует plan).
    from billing import services
    services.activate(sub, plan=plan_start)

    admin = SubscriptionAdmin(Subscription, site)
    admin.action_renew(_req(rf, superuser), Subscription.objects.filter(pk=sub.pk))

    sub.refresh_from_db()
    assert sub.status == Subscription.Status.ACTIVE


@pytest.mark.django_db
def test_action_renew_without_plan_reports_warning(clinic_a, superuser, site, rf):
    """action_renew на trialing-подписке без тарифа пропускает и сообщает WARNING."""
    sub = Subscription.objects.get(clinic=clinic_a)
    assert sub.plan is None  # триал без тарифа

    admin = SubscriptionAdmin(Subscription, site)
    req = _req(rf, superuser)
    admin.action_renew(req, Subscription.objects.filter(pk=sub.pk))

    sub.refresh_from_db()
    assert sub.status == Subscription.Status.TRIALING  # не изменился


@pytest.mark.django_db
def test_action_activate_pro(plan_pro, clinic_a, superuser, site, rf):
    """action_activate_pro переводит в active на тарифе pro."""
    sub = Subscription.objects.get(clinic=clinic_a)

    admin = SubscriptionAdmin(Subscription, site)
    admin.action_activate_pro(_req(rf, superuser), Subscription.objects.filter(pk=sub.pk))

    sub.refresh_from_db()
    assert sub.status == Subscription.Status.ACTIVE
    assert sub.plan.code == "pro"


@pytest.mark.django_db
def test_action_activate_pro_missing_plan(clinic_a, superuser, site, rf):
    """action_activate_pro без тарифа 'pro' в БД сообщает ERROR, подписку не меняет."""
    Plan.objects.filter(code="pro").delete()
    sub = Subscription.objects.get(clinic=clinic_a)

    admin = SubscriptionAdmin(Subscription, site)
    req = _req(rf, superuser)
    admin.action_activate_pro(req, Subscription.objects.filter(pk=sub.pk))

    sub.refresh_from_db()
    assert sub.status == Subscription.Status.TRIALING  # не тронута


@pytest.mark.django_db
def test_action_to_trial(plan_pro, clinic_a, superuser, site, rf):
    """action_to_trial переводит подписку в триал."""
    sub = Subscription.objects.get(clinic=clinic_a)
    from billing import services
    services.activate(sub, plan=plan_pro)

    admin = SubscriptionAdmin(Subscription, site)
    admin.action_to_trial(_req(rf, superuser), Subscription.objects.filter(pk=sub.pk))

    sub.refresh_from_db()
    assert sub.status == Subscription.Status.TRIALING
    assert sub.current_period_end is not None


@pytest.mark.django_db
def test_action_suspend(clinic_a, superuser, site, rf):
    """action_suspend приостанавливает подписку."""
    sub = Subscription.objects.get(clinic=clinic_a)

    admin = SubscriptionAdmin(Subscription, site)
    admin.action_suspend(_req(rf, superuser), Subscription.objects.filter(pk=sub.pk))

    sub.refresh_from_db()
    assert sub.status == Subscription.Status.SUSPENDED


# --------------------------------------------------------------------------- #
# PaymentAdmin.action_confirm_payment                                           #
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
def test_action_confirm_payment(plan_start, clinic_a, superuser, site, rf):
    """action_confirm_payment подтверждает pending-платёж → подписка active."""
    from providers.billing.factory import get_billing_provider
    sub = Subscription.objects.get(clinic=clinic_a)
    payment = get_billing_provider().create_payment(sub, plan_start)
    assert payment.status == Payment.Status.PENDING

    admin = PaymentAdmin(Payment, site)
    admin.action_confirm_payment(_req(rf, superuser), Payment.objects.filter(pk=payment.pk))

    payment.refresh_from_db()
    assert payment.status == Payment.Status.PAID

    sub.refresh_from_db()
    assert sub.status == Subscription.Status.ACTIVE


@pytest.mark.django_db
def test_action_confirm_payment_already_paid_skipped(plan_start, clinic_a, superuser, site, rf):
    """Уже оплаченный платёж пропускается (счётчик skipped, период не двигается)."""
    from providers.billing.factory import get_billing_provider
    from billing import services
    sub = Subscription.objects.get(clinic=clinic_a)
    services.activate(sub, plan=plan_start)
    payment = get_billing_provider().create_payment(sub, plan_start)
    get_billing_provider().confirm_payment(payment)
    period_end_before = sub.current_period_end

    admin = PaymentAdmin(Payment, site)
    req = _req(rf, superuser)
    admin.action_confirm_payment(req, Payment.objects.filter(pk=payment.pk))

    sub.refresh_from_db()
    # Период не сдвинулся (идемпотентность).
    assert sub.current_period_end == period_end_before


# --------------------------------------------------------------------------- #
# get_queryset скоупинг                                                         #
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
def test_subscription_scoped_to_clinic_user(clinic_a, clinic_b, clinic_user, site, rf):
    """ClinicUser видит только подписку своей клиники, не чужой."""
    admin = SubscriptionAdmin(Subscription, site)
    req = _req(rf, clinic_user)
    qs = admin.get_queryset(req)

    assert qs.count() == 1
    assert qs.first().clinic_id == clinic_a.pk


@pytest.mark.django_db
def test_subscription_superuser_sees_all(clinic_a, clinic_b, superuser, site, rf):
    """Суперадмин видит подписки всех клиник."""
    admin = SubscriptionAdmin(Subscription, site)
    req = _req(rf, superuser)
    qs = admin.get_queryset(req)

    clinic_ids = set(qs.values_list("clinic_id", flat=True))
    assert clinic_a.pk in clinic_ids
    assert clinic_b.pk in clinic_ids


@pytest.mark.django_db
def test_payment_scoped_to_clinic_user(plan_start, clinic_a, clinic_b, clinic_user, site, rf):
    """ClinicUser видит платежи только своей клиники."""
    from providers.billing.factory import get_billing_provider
    provider = get_billing_provider()

    sub_a = Subscription.objects.get(clinic=clinic_a)
    sub_b = Subscription.objects.get(clinic=clinic_b)
    provider.create_payment(sub_a, plan_start)
    provider.create_payment(sub_b, plan_start)

    admin = PaymentAdmin(Payment, site)
    req = _req(rf, clinic_user)
    qs = admin.get_queryset(req)

    assert qs.count() == 1
    assert qs.first().clinic_id == clinic_a.pk


@pytest.mark.django_db
def test_usage_scoped_to_clinic_user(clinic_a, clinic_b, clinic_user, site, rf):
    """ClinicUser видит счётчики только своей клиники."""
    from billing import services
    services.get_or_create_usage(clinic_a)
    services.get_or_create_usage(clinic_b)

    admin = UsageCounterAdmin(UsageCounter, site)
    req = _req(rf, clinic_user)
    qs = admin.get_queryset(req)

    assert qs.count() == 1
    assert qs.first().clinic_id == clinic_a.pk


@pytest.mark.django_db
def test_actions_empty_for_clinic_user(clinic_a, clinic_user, site, rf):
    """Клиника-пользователь не видит никаких actions в SubscriptionAdmin."""
    admin = SubscriptionAdmin(Subscription, site)
    req = _req(rf, clinic_user)
    actions = admin.get_actions(req)
    assert actions == {}
