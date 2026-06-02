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
    def generate(self, messages: list[ChatMessage], clinic: "Clinic") -> str:
        """Сгенерировать ответ ассистента.

        `messages` — история диалога (включая системный промпт первым элементом).
        `clinic` — клиника, под которую сформирован контекст (для выбора модели/тона).
        Возвращает текст ответа.
        """
        raise NotImplementedError

    @abstractmethod
    def transcribe(self, audio_bytes: bytes, language: str = "ru") -> str:
        """Расшифровать голосовое сообщение в текст (Whisper). Возвращает текст."""
        raise NotImplementedError
