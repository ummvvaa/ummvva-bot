"""Groq AI-провайдер. Текстовая генерация через chat.completions."""
from __future__ import annotations

import logging
import time
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
        self._max_retries: int = settings.AI_MAX_RETRIES

    def generate(
        self,
        messages: list[ChatMessage],
        clinic: "Clinic",
        json_mode: bool = False,
    ) -> str:
        import groq as groq_lib

        clinic_name = getattr(clinic, "name", "unknown")
        logger.info(
            "[groq] generate for %s, model=%s, json_mode=%s",
            clinic_name,
            self._model,
            json_mode,
        )

        # В json-режиме просим OpenAI-совместимый structured output. Groq требует,
        # чтобы слово "json" встречалось в промпте (это обеспечивает наш системный
        # промпт извлечения) — иначе API отклоняет response_format.
        extra: dict = {"response_format": {"type": "json_object"}} if json_mode else {}

        last_exc: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                completion = self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,  # type: ignore[arg-type]
                    temperature=self._temperature,
                    **extra,
                )
                return completion.choices[0].message.content or ""

            except groq_lib.APIStatusError as exc:
                # 4xx кроме 429 — это наша ошибка, ретраить бессмысленно.
                if exc.status_code not in (429,) and exc.status_code < 500:
                    raise
                last_exc = exc
                delay = 2 ** (attempt - 1)
                logger.warning(
                    "[groq] HTTP %d (attempt %d/%d) — retry in %ds",
                    exc.status_code,
                    attempt,
                    self._max_retries,
                    delay,
                )

            except groq_lib.APIConnectionError as exc:
                last_exc = exc
                delay = 2 ** (attempt - 1)
                logger.warning(
                    "[groq] connection error (attempt %d/%d) — retry in %ds",
                    attempt,
                    self._max_retries,
                    delay,
                )

            if attempt < self._max_retries:
                time.sleep(delay)  # type: ignore[possibly-undefined]

        raise last_exc  # type: ignore[misc]

    def transcribe(self, audio_bytes: bytes, mimetype: str) -> str | None:
        try:
            result = self._client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=("voice.ogg", audio_bytes),
            )
            return result.text
        except Exception as exc:
            logger.error("[groq] transcribe failed: %s", exc)
            return None
