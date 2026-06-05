"""
ManualBillingProvider — приём оплаты вручную (MVP, BILLING_PROVIDER=manual).

Никакого эквайера: владелец видит факт оплаты (перевод/Kaspi на счёт) и
подтверждает её в коде/admin → подписка продлевается. Основной провайдер до
подключения реального банка (KaspiBillingProvider).
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from billing import services
from billing.models import Payment, Plan, Subscription

from .base import BillingProvider

logger = logging.getLogger(__name__)


class ManualBillingProvider(BillingProvider):
    """Платёжный провайдер с подтверждением оплаты в коде/admin."""

    name = "manual"

    def create_payment(self, subscription: Subscription, plan: Plan) -> Payment:
        """Завести Payment(status="pending") на период тарифа от текущего момента."""
        now = timezone.now()
        payment = Payment.objects.create(
            clinic=subscription.clinic,
            subscription=subscription,
            plan=plan,
            amount_kzt=plan.price_kzt,
            provider=self.name,
            status=Payment.Status.PENDING,
            period_start=now,
            period_end=now + timedelta(days=plan.period_days),
        )
        logger.info(
            "[billing/manual] создан платёж #%s на %s₸ (клиника %s, тариф %s)",
            payment.pk, payment.amount_kzt, subscription.clinic_id, plan.code,
        )
        return payment

    def confirm_payment(self, payment: Payment) -> Payment:
        """Оплата подтверждена → paid + продление подписки. Идемпотентно."""
        # Идемпотентность: уже оплаченный платёж второй раз период НЕ двигает.
        if payment.status == Payment.Status.PAID:
            logger.info("[billing/manual] платёж #%s уже оплачен — пропуск", payment.pk)
            return payment

        payment.status = Payment.Status.PAID
        payment.paid_at = timezone.now()
        payment.save(update_fields=["status", "paid_at"])

        subscription = payment.subscription
        if subscription is None:
            logger.warning(
                "[billing/manual] платёж #%s без подписки — активация пропущена",
                payment.pk,
            )
            return payment

        # Подписка уже была активной с тарифом → продлеваем (renew, период
        # наращивается от старого конца); иначе (триал/past_due/suspended/без
        # тарифа) — активируем оплаченным тарифом (activate, период от now).
        if (
            subscription.status == Subscription.Status.ACTIVE
            and subscription.plan_id is not None
        ):
            services.renew(subscription)
        else:
            services.activate(subscription, plan=payment.plan)

        logger.info(
            "[billing/manual] платёж #%s подтверждён → подписка %s продлена",
            payment.pk, subscription.pk,
        )
        return payment

    def handle_webhook(self, payload: dict) -> Payment | None:
        """У manual нет внешнего колбэка — оплата подтверждается в коде/admin."""
        return None
