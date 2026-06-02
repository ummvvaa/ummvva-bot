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

    if name == "evolution":
        from .evolution import EvolutionWhatsAppProvider

        return EvolutionWhatsAppProvider()

    # meta (Cloud API) появится в Фазе 6.
    raise ValueError(
        f"Неизвестный или ещё не реализованный WHATSAPP_PROVIDER='{name}'. "
        "Доступно: mock, evolution."
    )
