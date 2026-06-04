"""Mock-реализация WhatsApp-провайдера. Работает без интернета, для тестов."""
from __future__ import annotations

import logging
import uuid

from .base import MediaFile, SendResult, WhatsAppProvider

logger = logging.getLogger(__name__)


class MockWhatsAppProvider(WhatsAppProvider):
    """Ничего не отправляет наружу — только логирует и возвращает заглушки.

    Хранит отправленные сообщения в `self.sent` — удобно проверять в тестах.
    """

    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send_message(self, to: str, text: str) -> SendResult:
        message_id = f"mock-{uuid.uuid4()}"
        self.sent.append({"to": to, "text": text, "message_id": message_id})
        logger.info("[mock-whatsapp] -> %s: %s", to, text)
        return SendResult(success=True, message_id=message_id, raw={"mock": True})

    def download_media(self, media_id: str) -> MediaFile:
        logger.info("[mock-whatsapp] download_media(%s)", media_id)
        # Возвращаем минимальную заглушку аудио.
        return MediaFile(
            content=b"mock-audio-bytes",
            mime_type="audio/ogg",
            filename=f"{media_id}.ogg",
        )

    def download_voice_media(self, message_key_id: str) -> tuple[bytes, str] | None:
        logger.info("[mock-whatsapp] download_voice_media(%s)", message_key_id)
        # Заглушка аудио — без интернета, для тестов голосовой ветки.
        return b"mock-audio-bytes", "audio/ogg"
