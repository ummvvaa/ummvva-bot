"""
KaspiBillingProvider — ЗАСТАБ (BILLING_PROVIDER=kaspi).

Аналог `meta` у WhatsApp-провайдера: КЛАСС существует и подключён в фабрику, но
методы поднимают NotImplementedError — для реальной оплаты через Kaspi нужен
договор с эквайером (мерчант-аккаунт, ключи API, согласование колбэков).

Что здесь будет, когда подключим Kaspi:
  • create_payment — создаст платёж на стороне Kaspi и вернёт Payment с external_id
    (id транзакции банка) и ссылкой на оплату для клиники (status="pending");
  • handle_webhook — примет колбэк банка об оплате, ПРОВЕРИТ ПОДПИСЬ запроса,
    найдёт Payment по external_id и вызовет confirm_payment (→ продление подписки);
  • confirm_payment — как у manual: пометит платёж paid + дёрнет activate/renew.
"""
from __future__ import annotations

from billing.models import Payment, Plan, Subscription

from .base import BillingProvider

_STUB_MESSAGE = (
    "KaspiBillingProvider ещё не реализован: требуется договор с эквайером "
    "(мерчант-аккаунт Kaspi, ключи API, согласование колбэков). "
    "Для MVP используйте BILLING_PROVIDER=manual."
)


class KaspiBillingProvider(BillingProvider):
    """Платёжный провайдер Kaspi — застаб до договора с эквайером."""

    name = "kaspi"

    def create_payment(self, subscription: Subscription, plan: Plan) -> Payment:
        raise NotImplementedError(_STUB_MESSAGE)

    def confirm_payment(self, payment: Payment) -> Payment:
        raise NotImplementedError(_STUB_MESSAGE)

    def handle_webhook(self, payload: dict) -> Payment | None:
        raise NotImplementedError(_STUB_MESSAGE)
