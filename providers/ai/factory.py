"""Фабрика AI-провайдера. Выбор реализации через settings.AI_PROVIDER."""
from __future__ import annotations

from functools import lru_cache

from django.conf import settings

from .base import AIProvider
from .mock import MockAIProvider


@lru_cache(maxsize=None)
def get_ai_provider() -> AIProvider:
    """Вернуть singleton-экземпляр выбранного AI-провайдера."""
    name = (settings.AI_PROVIDER or "mock").lower()

    if name == "mock":
        return MockAIProvider()

    if name == "groq":
        from .groq import GroqAIProvider
        return GroqAIProvider()

    # gemini появится в следующих фазах.
    raise ValueError(
        f"Неизвестный или ещё не реализованный AI_PROVIDER='{name}'. "
        "Доступно: mock, groq."
    )
