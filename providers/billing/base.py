"""
Абстракция платёжного провайдера (биллинг, Фаза 5).

НЕЗЫБЛЕМОЕ ПРАВИЛО: бизнес-логика НИКОГДА не работает с эквайером/банком напрямую,
только через этот интерфейс. Реализации: manual (MVP — оплата подтверждается в
коде/admin), kaspi (застаблен до договора с эквайером).
Выбор реализации — через переменную окружения BILLING_PROVIDER.

Деньги и переходы статусов подписки — единый источник истины в billing.services /
billing.models. Провайдер только создаёт Payment и дёргает активацию/продление.
Все datetime — timezone-aware, через django.utils.timezone.now().
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from billing.models import Payment, Plan, Subscription


class BillingProvider(ABC):
    """Базовый интерфейс для всех платёжных провайдеров."""

    @abstractmethod
    def create_payment(self, subscription: "Subscription", plan: "Plan") -> "Payment":
        """Создать платёж за период тарифа `plan` для подписки `subscription`.

        Возвращает Payment со status="pending" (ожидает оплаты).
        """
        raise NotImplementedError

    @abstractmethod
    def confirm_payment(self, payment: "Payment") -> "Payment":
        """Подтвердить оплату: status="paid" + активация/продление подписки.

        Должен быть ИДЕМПОТЕНТНЫМ: повторное подтверждение того же Payment не
        продлевает период второй раз.
        """
        raise NotImplementedError

    @abstractmethod
    def handle_webhook(self, payload: dict) -> "Payment | None":
        """Обработать колбэк платёжного провайдера (для будущих реальных эквайеров).

        Возвращает подтверждённый Payment или None, если колбэк ни к чему не привёл.
        Для manual всегда None — оплата подтверждается в коде/admin, не колбэком.
        """
        raise NotImplementedError
