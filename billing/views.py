"""
Webhook платёжного провайдера (биллинг, Фаза 5) — ЗАГЛУШКА-задел.

Реальные эквайеры (Kaspi и т.п.) шлют колбэк об оплате на этот endpoint. По
аналогии с whatsapp_webhook вью работает быстро: парсит JSON, передаёт его
провайдеру (handle_webhook) и отвечает 200.

Для manual провайдер вернёт None (no-op) — endpoint существует как задел под
будущую реальную интеграцию, боевой обработки тут пока нет.

CSRF выключен (источник внешний): DRF @api_view с пустым authentication_classes.
"""
from __future__ import annotations

import logging

from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from providers.billing.factory import get_billing_provider

logger = logging.getLogger(__name__)


@api_view(["POST"])
@authentication_classes([])  # внешний источник — без сессии/CSRF
@permission_classes([AllowAny])
def billing_webhook(request):
    """POST /billing/webhook/ — приём колбэка платёжного провайдера (задел)."""
    provider = get_billing_provider()
    try:
        payment = provider.handle_webhook(request.data)
    except NotImplementedError:
        # Провайдер-застаб (kaspi) ещё не принимает колбэки — это не ошибка вызова.
        logger.info("[billing] webhook: провайдер не поддерживает колбэки (застаб).")
        return Response({"status": "not_implemented"}, status=200)

    if payment is None:
        # manual / нечего обрабатывать — отвечаем 200, чтобы провайдер не ретраил.
        return Response({"status": "ignored"}, status=200)
    return Response({"status": "ok", "payment_id": payment.pk}, status=200)
