"""
Evolution API WhatsApp-провайдер (MVP).

Отправка/приём через self-hosted Evolution API (https://github.com/EvolutionAPI/evolution-api).
Подключается, когда WHATSAPP_PROVIDER=evolution. Для тестов без интернета остаётся mock.

ENV:
  EVOLUTION_API_URL  — базовый URL инстанса, напр. http://evolution:8080
  EVOLUTION_API_KEY  — глобальный ключ (заголовок `apikey`)
  EVOLUTION_INSTANCE — имя инстанса (к нему привязан номер по QR)
"""
from __future__ import annotations

import base64
import logging
from typing import Optional

import requests

from .base import MediaFile, SendResult, WhatsAppProvider

logger = logging.getLogger(__name__)

# Таймаут на запросы к Evolution API (сек).
_TIMEOUT = 15


class EvolutionWhatsAppProvider(WhatsAppProvider):
    """Реальная отправка через Evolution API.

    Базовый URL, ключ и имя инстанса берутся из settings (которые читают ENV).
    """

    def __init__(self, instance_name: str | None = None) -> None:
        from django.conf import settings

        base_url = (settings.EVOLUTION_API_URL or "").rstrip("/")
        api_key = settings.EVOLUTION_API_KEY or ""
        # Per-clinic instance_name overrides the global EVOLUTION_INSTANCE env var.
        instance = instance_name or (settings.EVOLUTION_INSTANCE or "")

        missing = [
            name
            for name, value in (
                ("EVOLUTION_API_URL", base_url),
                ("EVOLUTION_API_KEY", api_key),
                ("EVOLUTION_INSTANCE", instance),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "Не заданы переменные окружения для Evolution API: "
                + ", ".join(missing)
            )

        self._base_url = base_url
        self._api_key = api_key
        self._instance = instance

    @property
    def _headers(self) -> dict:
        return {"apikey": self._api_key, "Content-Type": "application/json"}

    def send_message(self, to: str, text: str) -> SendResult:
        """Отправить текст через Evolution API: POST /message/sendText/{instance}."""
        url = f"{self._base_url}/message/sendText/{self._instance}"
        # Evolution API v2: плоские поля number/text.
        payload = {"number": to, "text": text}

        logger.info("[evolution] -> %s (instance=%s)", to, self._instance)
        try:
            resp = requests.post(
                url, json=payload, headers=self._headers, timeout=_TIMEOUT
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            # Не роняем worker — логируем и возвращаем неуспех, чтобы вызвавший решил.
            logger.error("[evolution] ошибка отправки на %s: %s", to, exc)
            return SendResult(success=False, message_id=None, raw={"error": str(exc)})

        try:
            data = resp.json()
        except ValueError:
            data = {"raw_text": resp.text}

        # Evolution возвращает идентификатор в key.id.
        message_id = None
        if isinstance(data, dict):
            key = data.get("key")
            if isinstance(key, dict):
                message_id = key.get("id")

        logger.info("[evolution] отправлено, message_id=%s", message_id)
        return SendResult(success=True, message_id=message_id, raw=data)

    def download_voice_media(
        self, message_key_id: str
    ) -> Optional[tuple[bytes, str]]:
        """Скачать голосовое аудио из Evolution API по идентификатору сообщения.

        Evolution сам расшифровывает медиа WhatsApp и возвращает base64.
        Ручную крипту (libsignal) не используем.

        Returns:
            (audio_bytes, mimetype) или None, если медиа недоступно/ошибка.
        """
        url = f"{self._base_url}/chat/getBase64FromMediaMessage/{self._instance}"
        payload = {
            "message": {"key": {"id": message_key_id}},
            "convertToMp4": False,
        }

        logger.info(
            "[evolution] запрос медиа message_key_id=%s (instance=%s)",
            message_key_id,
            self._instance,
        )
        try:
            resp = requests.post(
                url, json=payload, headers=self._headers, timeout=_TIMEOUT
            )
            resp.raise_for_status()
        except requests.HTTPError as exc:
            logger.warning(
                "[evolution] медиа недоступно (HTTP %s) для message_key_id=%s: %s",
                exc.response.status_code if exc.response is not None else "?",
                message_key_id,
                exc,
            )
            return None
        except requests.RequestException as exc:
            logger.error(
                "[evolution] ошибка сети при скачивании медиа message_key_id=%s: %s",
                message_key_id,
                exc,
            )
            return None

        try:
            data = resp.json()
        except ValueError:
            logger.error(
                "[evolution] не удалось разобрать JSON ответа для message_key_id=%s",
                message_key_id,
            )
            return None

        b64 = data.get("base64") if isinstance(data, dict) else None
        if not b64:
            logger.warning(
                "[evolution] пустой base64 для message_key_id=%s (медиа просрочено?)",
                message_key_id,
            )
            return None

        try:
            audio_bytes = base64.b64decode(b64)
        except Exception as exc:
            logger.error(
                "[evolution] ошибка декодирования base64 для message_key_id=%s: %s",
                message_key_id,
                exc,
            )
            return None

        mimetype: str = data.get("mimetype") or "audio/ogg"
        logger.info(
            "[evolution] медиа получено: %d байт, mimetype=%s",
            len(audio_bytes),
            mimetype,
        )
        return audio_bytes, mimetype

    def download_media(self, media_id: str) -> MediaFile:
        """Скачать медиа по media_id (общий интерфейс провайдера).

        Для голосовых используй download_voice_media(message_key_id).
        Этот метод требует message-объект, а не просто id — см. download_voice_media.
        """
        raise NotImplementedError(
            "Используй download_voice_media(message_key_id) для Evolution. "
            "download_media с чистым media_id не поддерживается провайдером."
        )
