# Generated manually 2026-06-05 — Фаза 5: data-миграция биллинга.
#
# Делает две вещи:
#   1) Заводит два тарифа-плейсхолдера: "start" и "pro". ЦЕНЫ — ЗАГЛУШКИ
#      (15000 / 30000 ₸); владелец поправит их в Django admin. У "pro" лимит
#      сообщений = null (безлимит).
#   2) Бэкфилл: для КАЖДОЙ уже существующей клиники без подписки создаёт пробную
#      подписку (trialing, trial_end = now + TRIAL_DAYS), чтобы прод не сломался
#      после деплоя (подписку для НОВЫХ клиник заводит сигнал post_save, но старые
#      клиники созданы до появления приложения billing).
#
# Все datetime — timezone-aware (timezone.now()). Деньги — Decimal, без float.
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import migrations
from django.utils import timezone


def seed_plans_and_backfill(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    Clinic = apps.get_model("clinics", "Clinic")
    Subscription = apps.get_model("billing", "Subscription")

    # --- 1. Тарифы-плейсхолдеры (цены — заглушки, правятся в admin) ---
    Plan.objects.update_or_create(
        code="start",
        defaults={
            "name": "Старт",
            "price_kzt": Decimal("15000.00"),
            "period_days": 30,
            "message_limit": 1000,
            "is_active": True,
        },
    )
    Plan.objects.update_or_create(
        code="pro",
        defaults={
            "name": "Про",
            "price_kzt": Decimal("30000.00"),
            "period_days": 30,
            "message_limit": None,  # безлимит
            "is_active": True,
        },
    )

    # --- 2. Бэкфилл триала для существующих клиник без подписки ---
    now = timezone.now()
    trial_end = now + timedelta(days=settings.TRIAL_DAYS)
    for clinic in Clinic.objects.filter(subscription__isnull=True):
        Subscription.objects.create(
            clinic=clinic,
            status="trialing",
            trial_end=trial_end,
            current_period_start=now,
            current_period_end=trial_end,
        )


def reverse_noop(apps, schema_editor):
    # Откат не разрушаем: тарифы/подписки оставляем (их безопаснее удалит обратная
    # schema-миграция при сносе таблиц). Бэкфилл идемпотентен по subscription__isnull.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0001_initial"),
        ("clinics", "0004_backfill_instance_name"),
    ]

    operations = [
        migrations.RunPython(seed_plans_and_backfill, reverse_noop),
    ]
