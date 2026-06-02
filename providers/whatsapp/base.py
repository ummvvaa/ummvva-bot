"""
Абстракция WhatsApp-провайдера.

НЕЗЫБЛЕМОЕ ПРАВИЛО: бизнес-логика НИКОГДА не вызывает WhatsApp напрямую,
только через этот интерфейс. Реализации: mock, evolution, meta.
Выбор реализации — через переменную окружения WHATSAPP_PROVIDER.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SendResult:
    """Результат отправки сообщения."""

    success: bool
    message_id: str | None = None
    raw: dict | None = None


@dataclass
class MediaFile:
    """Скачанный медиафайл (например, голосовое сообщение)."""

    content: bytes
    mime_type: str
    filename: str | None = None


class WhatsAppProvider(ABC):
    """Базовый интерфейс для всех WhatsApp-провайдеров."""

    @abstractmethod
    def send_message(self, to: str, text: str) -> SendResult:
        """Отправить текстовое сообщение получателю `to` (номер в формате E.164)."""
        raise NotImplementedError

    @abstractmethod
    def download_media(self, media_id: str) -> MediaFile:
        """Скачать медиафайл по его идентификатору от провайдера."""
        raise NotImplementedError
