"""Фабрика WhatsApp-провайдера. Выбор реализации через settings.WHATSAPP_PROVIDER."""
from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from django.conf import settings

from .base import WhatsAppProvider
from .mock import MockWhatsAppProvider

if TYPE_CHECKING:
    from clinics.models import Clinic


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


def get_whatsapp_provider_for_clinic(clinic: "Clinic") -> WhatsAppProvider:
    """Провайдер для конкретной клиники, использующий её instance_name.

    Для Evolution: каждая клиника имеет свой инстанс (Clinic.instance_name).
    Сообщения уходят именно с того подключения, которое привязано к клинике.
    Для mock: возвращает глобальный singleton (изоляция обеспечивается тестами).
    """
    name = (settings.WHATSAPP_PROVIDER or "mock").lower()

    if name == "mock":
        return get_whatsapp_provider()

    if name == "evolution":
        instance = (clinic.instance_name or "").strip() or None
        return _get_evolution_for_instance(instance)

    # meta (Cloud API) появится в Фазе 6.
    raise ValueError(
        f"Неизвестный или ещё не реализованный WHATSAPP_PROVIDER='{name}'. "
        "Доступно: mock, evolution."
    )


@lru_cache(maxsize=None)
def _get_evolution_for_instance(instance_name: str | None) -> WhatsAppProvider:
    """Закешированный Evolution-провайдер для конкретного инстанса."""
    from .evolution import EvolutionWhatsAppProvider

    return EvolutionWhatsAppProvider(instance_name=instance_name)
