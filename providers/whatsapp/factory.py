"""Фабрика WhatsApp-провайдера. Выбор реализации через settings.WHATSAPP_PROVIDER."""
from __future__ import annotations

from functools import lru_cache

from django.conf import settings

from .base import WhatsAppProvider
from .mock import MockWhatsAppProvider


@lru_cache(maxsize=None)
def get_whatsapp_provider() -> WhatsAppProvider:
    """Вернуть singleton-экземпляр выбранного WhatsApp-провайдера."""
    name = (settings.WHATSAPP_PROVIDER or "mock").lower()

    if name == "mock":
        return MockWhatsAppProvider()

    # evolution и meta появятся в следующих фазах.
    raise ValueError(
        f"Неизвестный или ещё не реализованный WHATSAPP_PROVIDER='{name}'. "
        "Доступно: mock."
    )
