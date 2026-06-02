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

import logging

import requests

from .base import MediaFile, SendResult, WhatsAppProvider

logger = logging.getLogger(__name__)

# Таймаут на запросы к Evolution API (сек).
_TIMEOUT = 15


class EvolutionWhatsAppProvider(WhatsAppProvider):
    """Реальная отправка через Evolution API.

    Базовый URL, ключ и имя инстанса берутся из settings (которые читают ENV).
    """

    def __init__(self) -> None:
        from django.conf import settings

        base_url = (settings.EVOLUTION_API_URL or "").rstrip("/")
        api_key = settings.EVOLUTION_API_KEY or ""
        instance = settings.EVOLUTION_INSTANCE or ""

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

    def download_media(self, media_id: str) -> MediaFile:
        """Скачать медиа (голос/фото) по идентификатору.

        TODO (Фаза 2): уточнить формат. В Evolution API медиа достаётся через
        POST /chat/getBase64FromMediaMessage/{instance} с телом, содержащим
        сам объект message (а не просто media_id). Здесь нужно будет либо
        принимать base64 прямо из вебхука, либо хранить message-объект.
        Пока формат не зафиксирован — поднимаем явную ошибку, чтобы не
        делать вид, что работает.
        """
        raise NotImplementedError(
            "download_media для Evolution появится в Фазе 2 (голосовые). "
            "Нужно зафиксировать формат medi-объекта из вебхука."
        )
