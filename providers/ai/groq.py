"""Groq AI-провайдер. Текстовая генерация через chat.completions."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .base import AIProvider, ChatMessage

if TYPE_CHECKING:
    from clinics.models import Clinic

logger = logging.getLogger(__name__)


class GroqAIProvider(AIProvider):
    def __init__(self) -> None:
        from groq import Groq
        from django.conf import settings

        if not settings.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY не задан — установи его в .env")

        self._client = Groq(api_key=settings.GROQ_API_KEY)
        self._model: str = settings.GROQ_MODEL
        self._temperature: float = settings.GROQ_TEMPERATURE

    def generate(self, messages: list[ChatMessage], clinic: "Clinic") -> str:
        clinic_name = getattr(clinic, "name", "unknown")
        logger.info("[groq] generate for %s, model=%s", clinic_name, self._model)

        completion = self._client.chat.completions.create(
            model=self._model,
            messages=messages,  # type: ignore[arg-type]
            temperature=self._temperature,
        )
        return completion.choices[0].message.content or ""

    def transcribe(self, audio_bytes: bytes, language: str = "ru") -> str:
        # Реализуется в Фазе 2 (Whisper через Groq).
        raise NotImplementedError("transcribe появится в Фазе 2")
