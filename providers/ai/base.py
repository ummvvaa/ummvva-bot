"""
Абстракция AI-провайдера.

НЕЗЫБЛЕМОЕ ПРАВИЛО: бизнес-логика НИКОГДА не вызывает AI напрямую,
только через этот интерфейс. Реализации: mock, groq, gemini.
Выбор реализации — через переменную окружения AI_PROVIDER.

«Обучение» под клинику — это НЕ файнтюнинг: данные клиники подаются
в системный промпт. Модель не дообучается.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from clinics.models import Clinic


class ChatMessage(TypedDict):
    """Одно сообщение в формате OpenAI-совместимого чата."""

    role: str  # "system" | "user" | "assistant"
    content: str


class AIProvider(ABC):
    """Базовый интерфейс для всех AI-провайдеров."""

    @abstractmethod
    def generate(
        self,
        messages: list[ChatMessage],
        clinic: "Clinic",
        json_mode: bool = False,
    ) -> str:
        """Сгенерировать ответ ассистента.

        `messages` — история диалога (включая системный промпт первым элементом).
        `clinic` — клиника, под которую сформирован контекст (для выбора модели/тона).
        `json_mode` — если True, модель должна вернуть СТРОГО JSON-объект без
        преамбулы и markdown (structured output). Используется для извлечения
        структурированных данных (например, намерения записаться — Фаза 3).
        Возвращает текст ответа (в json_mode — строку с JSON).
        """
        raise NotImplementedError

    @abstractmethod
    def transcribe(self, audio_bytes: bytes, mimetype: str) -> str | None:
        """Расшифровать голосовое сообщение в текст (Whisper).

        `mimetype` — MIME-тип аудио, например "audio/ogg;codecs=opus".
        Возвращает распознанный текст или None при ошибке.
        """
        raise NotImplementedError
