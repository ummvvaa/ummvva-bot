"""
Сигналы биллинга.

При СОЗДАНИИ клиники автоматически заводим ей пробную подписку (trialing) на
settings.TRIAL_DAYS дней, чтобы новая клиника сразу могла работать, а биллинг знал
о ней. get_or_create — чтобы повторный save клиники не плодил подписки.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from clinics.models import Clinic
from .models import Subscription


@receiver(post_save, sender=Clinic, dispatch_uid="billing_create_trial_subscription")
def create_trial_subscription(sender, instance: Clinic, created: bool, **kwargs) -> None:
    if not created:
        return

    now = timezone.now()
    trial_end = now + timedelta(days=settings.TRIAL_DAYS)

    Subscription.objects.get_or_create(
        clinic=instance,
        defaults={
            "status": Subscription.Status.TRIALING,
            "trial_end": trial_end,
            "current_period_start": now,
            "current_period_end": trial_end,
        },
    )
