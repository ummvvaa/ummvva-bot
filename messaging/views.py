"""
Webhook приёма входящих WhatsApp-сообщений (Evolution API, событие MESSAGES_UPSERT).

Принцип: вью работает БЫСТРО и НЕ обрабатывает сообщение синхронно — иначе
провайдер словит таймаут и начнёт слать ретраи (дубли). Поэтому:
  1. проверяем секрет (внешний источник);
  2. валидируем/парсим payload;
  3. ставим задачу в Celery (handle_incoming_message.delay);
  4. сразу отвечаем 200.

CSRF выключен (источник внешний): DRF @api_view с пустым authentication_classes
не применяет CSRF-проверку сессии. Доступ ограничен секретом, а не сессией Django.
"""
from __future__ import annotations

import logging

from django.conf import settings
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from messaging.tasks import handle_incoming_message
from messaging.webhook_parser import parse_evolution_payload

logger = logging.getLogger(__name__)


def _token_ok(request) -> bool:
    """Проверить секрет webhook.

    Секрет задаётся в settings.WHATSAPP_WEBHOOK_TOKEN и передаётся провайдером
    либо в заголовке `X-Webhook-Token`, либо в query-параметре `token`
    (URL вебхука мы прописываем сами при настройке инстанса).

    Если секрет не сконфигурирован — в dev пропускаем с предупреждением
    (по умолчанию провайдеры = mock, внешнего трафика нет).
    """
    expected = getattr(settings, "WHATSAPP_WEBHOOK_TOKEN", "") or ""
    if not expected:
        logger.warning(
            "WHATSAPP_WEBHOOK_TOKEN не задан — webhook открыт. Задай секрет для прода."
        )
        return True
    provided = request.headers.get("X-Webhook-Token") or request.query_params.get("token")
    return provided == expected


@api_view(["POST"])
@authentication_classes([])  # внешний источник — без сессии/CSRF
@permission_classes([AllowAny])
def whatsapp_webhook(request):
    """POST /webhook/whatsapp/ — приём входящих от Evolution API."""
    if not _token_ok(request):
        logger.warning("Webhook: неверный или отсутствующий секрет — 403.")
        return Response({"detail": "forbidden"}, status=403)

    incoming = parse_evolution_payload(request.data)
    if incoming is None:
        # Нечего обрабатывать (эхо/группа/не-текст/неполные данные).
        # Отвечаем 200, чтобы провайдер не ретраил.
        return Response({"status": "ignored"}, status=200)

    # Ставим задачу и СРАЗУ отвечаем — никакой синхронной обработки.
    handle_incoming_message.delay(
        clinic_number=incoming.clinic_number,
        customer_phone=incoming.customer_phone,
        text=incoming.text,
        external_id=incoming.external_id,
        instance_name=incoming.instance_name,
        message_type=incoming.message_type,
        push_name=incoming.push_name,
    )
    return Response({"status": "accepted"}, status=200)
