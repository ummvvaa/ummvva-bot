"""
Разбор входящего webhook-payload от Evolution API (событие MESSAGES_UPSERT).

Задача парсера — быстро и ТОЛЕРАНТНО вытащить из «сырого» payload то, что нужно
для маршрутизации и обработки:
  • clinic_number  — номер-получатель (наш номер клиники, по нему ищем Clinic);
  • customer_phone — номер отправителя (клиент);
  • text           — текст сообщения;
  • external_id    — ID сообщения у провайдера (для дедупликации входящих).

Если payload не похож на входящее текстовое сообщение от клиента (эхо нашего
исходящего, групповой чат, не-текст, нет текста) — возвращаем None, и webhook
просто ответит 200 без постановки задачи.

Формат payload Evolution API v2 (упрощённо):
    {
      "event": "messages.upsert",
      "instance": "clinic1",
      "sender": "77001112233@s.whatsapp.net",   # наш номер (владелец инстанса)
      "data": {
        "key": {
          "remoteJid": "77009998877@s.whatsapp.net",  # номер клиента (чат)
          "fromMe": false,
          "id": "BAE5F0..."
        },
        "pushName": "客户",
        "message": {"conversation": "Здравствуйте"},
        "messageType": "conversation"
      }
    }
"""
from __future__ import annotations

from dataclasses import dataclass


# Типы messageType (Evolution), которые считаем голосовыми.
VOICE_MESSAGE_TYPES = ("audioMessage", "pttMessage")


@dataclass
class IncomingMessage:
    """Извлечённые из webhook поля входящего сообщения."""

    clinic_number: str        # номер-получатель (наш номер клиники)
    customer_phone: str       # номер отправителя (клиент)
    text: str                 # текст сообщения (для голосового — пустой до транскрипции)
    external_id: str | None   # ID сообщения у провайдера / key.id (дедуп + скачивание медиа)
    message_type: str = "conversation"  # тип входящего (conversation, audioMessage, …)


def _strip_jid(jid: str | None) -> str:
    """Из WhatsApp JID вытащить чистый номер.

    "77001234567@s.whatsapp.net" -> "77001234567"
    "77001234567:12@s.whatsapp.net" -> "77001234567" (отбрасываем device-суффикс)
    """
    if not jid:
        return ""
    return jid.split("@", 1)[0].split(":", 1)[0].strip()


def _extract_text(message: object) -> str:
    """Достать текст из объекта message (поддерживаем основные текстовые типы)."""
    if not isinstance(message, dict):
        return ""
    # Обычное текстовое сообщение.
    conversation = message.get("conversation")
    if isinstance(conversation, str) and conversation.strip():
        return conversation.strip()
    # Текст с цитированием/превью ссылки.
    ext = message.get("extendedTextMessage")
    if isinstance(ext, dict):
        text = ext.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    return ""


def parse_evolution_payload(payload: object) -> IncomingMessage | None:
    """Разобрать payload Evolution API. Вернуть IncomingMessage или None.

    None означает «нечего обрабатывать» (эхо, группа, не-текст, неполные данные).
    """
    if not isinstance(payload, dict):
        return None

    data = payload.get("data")
    if not isinstance(data, dict):
        return None

    key = data.get("key")
    if not isinstance(key, dict):
        return None

    # Эхо нашего собственного исходящего сообщения — игнорируем.
    if key.get("fromMe"):
        return None

    remote_jid = key.get("remoteJid") or ""
    # Групповые чаты (…@g.us) и широковещалки в MVP не обрабатываем.
    if remote_jid.endswith("@g.us") or remote_jid.endswith("@broadcast"):
        return None

    customer_phone = _strip_jid(remote_jid)

    # Наш номер (получатель) — владелец инстанса. В payload Evolution это
    # верхнеуровневое поле `sender`; на всякий случай смотрим и data.owner.
    clinic_number = _strip_jid(
        payload.get("sender") or data.get("owner") or ""
    )

    text = _extract_text(data.get("message"))

    external_id = key.get("id") or None

    message_type = data.get("messageType") or "conversation"
    is_voice = message_type in VOICE_MESSAGE_TYPES

    # Маршрутизация невозможна без номеров — отбрасываем.
    if not clinic_number or not customer_phone:
        return None
    # Голосовое: текста ещё нет (транскрипция в Celery), но нужен key.id для скачивания.
    if is_voice:
        if not external_id:
            return None
    # Текстовое: без текста обрабатывать нечего.
    elif not text:
        return None

    return IncomingMessage(
        clinic_number=clinic_number,
        customer_phone=customer_phone,
        text=text,
        external_id=external_id,
        message_type=message_type,
    )
