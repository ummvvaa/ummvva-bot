"""Mock-реализация AI-провайдера. Работает без интернета, для тестов."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .base import AIProvider, ChatMessage

if TYPE_CHECKING:
    from clinics.models import Clinic

logger = logging.getLogger(__name__)


class MockAIProvider(AIProvider):
    """Возвращает детерминированные заглушки вместо вызова реального API."""

    def generate(self, messages: list[ChatMessage], clinic: "Clinic") -> str:
        last_user = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"),
            "",
        )
        clinic_name = getattr(clinic, "name", "клиника")
        logger.info("[mock-ai] generate for %s, last user msg: %r", clinic_name, last_user)
        return (
            f"[mock-ответ от «{clinic_name}»] "
            f"Здравствуйте! Я получил ваше сообщение: «{last_user}». "
            "Это заглушка ответа — реальный AI подключим в следующей фазе."
        )

    def transcribe(self, audio_bytes: bytes, language: str = "ru") -> str:
        logger.info("[mock-ai] transcribe %d bytes, lang=%s", len(audio_bytes), language)
        return "[mock-расшифровка голосового сообщения]"
