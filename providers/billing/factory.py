"""Фабрика платёжного провайдера. Выбор реализации через settings.BILLING_PROVIDER."""
from __future__ import annotations

from functools import lru_cache

from django.conf import settings

from .base import BillingProvider
from .manual import ManualBillingProvider


@lru_cache(maxsize=None)
def get_billing_provider() -> BillingProvider:
    """Вернуть singleton-экземпляр выбранного платёжного провайдера."""
    name = (settings.BILLING_PROVIDER or "manual").lower()

    if name == "manual":
        return ManualBillingProvider()

    if name == "kaspi":
        from .kaspi import KaspiBillingProvider

        return KaspiBillingProvider()

    raise ValueError(
        f"Неизвестный или ещё не реализованный BILLING_PROVIDER='{name}'. "
        "Доступно: manual, kaspi."
    )
