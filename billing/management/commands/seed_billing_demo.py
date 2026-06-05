"""
Management-команда: создать три тестовые клиники с разными состояниями подписки.

Состояния:
  • «Триал»     — trialing, период активен (14 дней от now);
  • «Активная»  — active, оплачена, период активен (30 дней от now);
  • «Просрочена» — suspended, период давно кончился (2 месяца назад).

Команда идемпотентна: повторный запуск находит клиники по instance_name и
обновляет их состояние подписки до актуального (дубли не плодит).

Использование:
    docker compose exec web python manage.py seed_billing_demo
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from billing import services
from billing.models import BillingEventLog, Plan, Subscription
from clinics.models import Clinic

# Уникальные instance_name для идемпотентности.
INSTANCE_TRIAL = "billing-demo-trial"
INSTANCE_ACTIVE = "billing-demo-active"
INSTANCE_SUSPENDED = "billing-demo-suspended"


def _get_or_create_plan() -> Plan:
    plan, _ = Plan.objects.get_or_create(
        code="billing_demo",
        defaults={
            "name": "Демо-тариф (billing demo)",
            "price_kzt": Decimal("15000"),
            "period_days": 30,
            "message_limit": 500,
        },
    )
    return plan


def _get_or_create_clinic(instance_name: str, name: str, number: str) -> tuple[Clinic, bool]:
    return Clinic.objects.get_or_create(
        instance_name=instance_name,
        defaults={
            "name": name,
            "whatsapp_number": number,
            "is_active": True,
            "notifications_enabled": True,
            "manager_whatsapp": number,
            "services_json": [{"name": "Профессиональная чистка", "price": "14 000 ₸"}],
        },
    )


def _set_trialing(clinic: Clinic) -> Subscription:
    sub = clinic.subscription
    now = timezone.now()
    trial_end = now + timedelta(days=14)
    sub.plan = None
    sub.status = Subscription.Status.TRIALING
    sub.current_period_start = now
    sub.current_period_end = trial_end
    sub.trial_end = trial_end
    sub.canceled_at = None
    sub.save()
    # Сброс старых событий периода (идемпотентность seed).
    BillingEventLog.objects.filter(subscription=sub).delete()
    return sub


def _set_active(clinic: Clinic, plan: Plan) -> Subscription:
    sub = clinic.subscription
    now = timezone.now()
    sub.plan = plan
    sub.status = Subscription.Status.ACTIVE
    sub.current_period_start = now
    sub.current_period_end = now + timedelta(days=30)
    sub.trial_end = None
    sub.canceled_at = None
    sub.save()
    BillingEventLog.objects.filter(subscription=sub).delete()
    return sub


def _set_suspended(clinic: Clinic, plan: Plan) -> Subscription:
    sub = clinic.subscription
    now = timezone.now()
    # Период кончился 2 месяца назад — давно за грейсом.
    period_end = now - timedelta(days=60)
    sub.plan = plan
    sub.status = Subscription.Status.SUSPENDED
    sub.current_period_start = period_end - timedelta(days=30)
    sub.current_period_end = period_end
    sub.trial_end = None
    sub.canceled_at = None
    sub.save()
    BillingEventLog.objects.filter(subscription=sub).delete()
    return sub


class Command(BaseCommand):
    help = (
        "Создать три демо-клиники с разными состояниями подписки: "
        "trialing / active / suspended. Идемпотентна."
    )

    def handle(self, *args, **options):
        plan = _get_or_create_plan()
        self.stdout.write(f"Тариф: {plan} (id={plan.pk})")

        # ── Триал ────────────────────────────────────────────────────────────
        clinic_t, created_t = _get_or_create_clinic(
            INSTANCE_TRIAL, "Демо-Триал", "79800000001"
        )
        sub_t = _set_trialing(clinic_t)
        self.stdout.write(
            self.style.SUCCESS(
                f"\n[1] Триал (id={clinic_t.pk}, instance={INSTANCE_TRIAL})\n"
                f"    Статус подписки: {sub_t.status}\n"
                f"    Конец периода:   {sub_t.current_period_end:%Y-%m-%d %H:%M}\n"
                f"    Обслуживается:   {services.is_clinic_serviceable(clinic_t)}"
            )
        )

        # ── Активная ─────────────────────────────────────────────────────────
        clinic_a, created_a = _get_or_create_clinic(
            INSTANCE_ACTIVE, "Демо-Активная", "79800000002"
        )
        sub_a = _set_active(clinic_a, plan)
        self.stdout.write(
            self.style.SUCCESS(
                f"\n[2] Активная (id={clinic_a.pk}, instance={INSTANCE_ACTIVE})\n"
                f"    Статус подписки: {sub_a.status}\n"
                f"    Конец периода:   {sub_a.current_period_end:%Y-%m-%d %H:%M}\n"
                f"    Обслуживается:   {services.is_clinic_serviceable(clinic_a)}"
            )
        )

        # ── Просрочена ───────────────────────────────────────────────────────
        clinic_s, created_s = _get_or_create_clinic(
            INSTANCE_SUSPENDED, "Демо-Просрочена", "79800000003"
        )
        sub_s = _set_suspended(clinic_s, plan)
        self.stdout.write(
            self.style.WARNING(
                f"\n[3] Просрочена (id={clinic_s.pk}, instance={INSTANCE_SUSPENDED})\n"
                f"    Статус подписки: {sub_s.status}\n"
                f"    Конец периода:   {sub_s.current_period_end:%Y-%m-%d %H:%M}\n"
                f"    Обслуживается:   {services.is_clinic_serviceable(clinic_s)}"
            )
        )

        new_count = sum([created_t, created_a, created_s])
        self.stdout.write(
            f"\n{'Создано' if new_count else 'Обновлено'}: "
            f"{new_count} новых / {3 - new_count} обновлено.\n"
            "Готово. Используй test_billing_flow для сквозной проверки."
        )
