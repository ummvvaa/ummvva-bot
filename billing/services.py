"""
Сервисный слой подписки (Фаза 5) — «мозг» биллинга.

ЧИСТАЯ логика + работа с БД. БЕЗ сети: ничего не знает о WhatsApp/Groq/Celery.
Его дёргают пайплайн (гейт обслуживания) и Celery-задачи (продление/суспенд).

ЕДИНЫЙ ИСТОЧНИК ИСТИНЫ для переходов статусов подписки. Любая смена
`Subscription.status` должна идти ТОЛЬКО через функции этого модуля (activate /
renew / mark_past_due / suspend / cancel) — никаких ручных `subscription.status = …`
в других местах. Так переходы логируются и остаются предсказуемыми.

Деньги тут не считаем (это модели/платежи) — только состояние подписки и учёт.
Все datetime — timezone-aware, через django.utils.timezone.now() (проект на
Asia/Almaty, USE_TZ=True).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import F
from django.utils import timezone

from clinics.models import Clinic
from .models import BillingEventLog, Subscription, UsageCounter

logger = logging.getLogger(__name__)

# Статусы, при которых клиника считается «в строю» (до проверки периода+grace).
# PAST_DUE включён намеренно: после того как ежедневный billing-cycle пометил
# просроченную подписку как past_due, бот должен продолжать обслуживать клинику в
# течение грейс-периода (проверку now < period_end + GRACE_DAYS делает гейт ниже).
# Грейс истечёт → cycle переведёт в suspended, и эта проверка вернёт False.
_SERVICEABLE_STATUSES = (
    Subscription.Status.TRIALING,
    Subscription.Status.ACTIVE,
    Subscription.Status.PAST_DUE,
)


def _get_subscription(clinic: Clinic) -> Subscription | None:
    """Подписка клиники или None (без исключения, если её ещё нет)."""
    try:
        return clinic.subscription
    except Subscription.DoesNotExist:
        return None


# --------------------------------------------------------------------------- #
# 1. Гейт обслуживания                                                         #
# --------------------------------------------------------------------------- #
def is_clinic_serviceable(clinic: Clinic) -> bool:
    """True, ТОЛЬКО если клиника вправе пользоваться ботом прямо сейчас.

    Условия (все обязательны):
      • clinic.is_active;
      • есть подписка со status in (trialing, active);
      • now < current_period_end + GRACE_DAYS.

    Учёт grace делает гейт корректным, даже если Celery-задача суспенда ещё не
    отработала (период кончился минуту назад — добиваем оплаченным грейсом).

    Никаких исключений наружу: при любой неполноте данных → False.
    """
    if clinic is None or not clinic.is_active:
        return False

    sub = _get_subscription(clinic)
    if sub is None:
        return False

    if sub.status not in _SERVICEABLE_STATUSES:
        return False

    if sub.current_period_end is None:
        return False

    deadline = sub.current_period_end + timedelta(days=settings.GRACE_DAYS)
    return timezone.now() < deadline


# --------------------------------------------------------------------------- #
# 2. Старт пробного периода                                                    #
# --------------------------------------------------------------------------- #
def start_trial(clinic: Clinic) -> Subscription:
    """Завести клинике пробную подписку. Идемпотентно (get_or_create).

    Подстраховка на случай, если post_save-сигнал по какой-то причине не сработал:
    повторный вызов не плодит подписки, а возвращает существующую.
    """
    now = timezone.now()
    trial_end = now + timedelta(days=settings.TRIAL_DAYS)

    sub, created = Subscription.objects.get_or_create(
        clinic=clinic,
        defaults={
            "status": Subscription.Status.TRIALING,
            "trial_end": trial_end,
            "current_period_start": now,
            "current_period_end": trial_end,
        },
    )
    if created:
        logger.info("[billing] триал заведён для клиники %s до %s", clinic.pk, trial_end)
    return sub


# --------------------------------------------------------------------------- #
# 3-5. Переходы статусов (единственная точка смены status)                     #
# --------------------------------------------------------------------------- #
def activate(
    subscription: Subscription,
    *,
    plan,
    period_start: datetime | None = None,
    period_days: int | None = None,
) -> Subscription:
    """Перевести подписку в active («оплатил — продлеваем»).

    Работает и из trialing, и из past_due/suspended (восстановление после оплаты):
    проставляет тариф, новые границы периода и обнуляет canceled_at.
    """
    start = period_start or timezone.now()
    days = period_days if period_days is not None else plan.period_days

    old_status = subscription.status
    subscription.plan = plan
    subscription.status = Subscription.Status.ACTIVE
    subscription.current_period_start = start
    subscription.current_period_end = start + timedelta(days=days)
    subscription.canceled_at = None
    subscription.save()

    logger.info(
        "[billing] подписка %s: %s → active (тариф %s, период %s…%s)",
        subscription.pk, old_status, plan.code,
        start, subscription.current_period_end,
    )
    return subscription


def renew(subscription: Subscription) -> Subscription:
    """Продлить подписку на следующий период тем же тарифом.

    Новое начало периода = старый конец (или now, если уже просрочен) — так
    непрерывная оплата не «съедает» дни. Новый конец = начало + plan.period_days.
    """
    plan = subscription.plan
    if plan is None:
        raise ValueError("Нельзя продлить подписку без тарифа (plan is None)")

    now = timezone.now()
    old_end = subscription.current_period_end
    new_start = old_end if (old_end is not None and old_end > now) else now
    new_end = new_start + timedelta(days=plan.period_days)

    old_status = subscription.status
    subscription.current_period_start = new_start
    subscription.current_period_end = new_end
    subscription.status = Subscription.Status.ACTIVE
    subscription.save()

    logger.info(
        "[billing] подписка %s: %s → active (продлена %s…%s)",
        subscription.pk, old_status, new_start, new_end,
    )
    return subscription


def mark_past_due(subscription: Subscription) -> Subscription:
    """Период кончился, оплаты нет → past_due (грейс-период, бот ещё работает)."""
    old_status = subscription.status
    subscription.status = Subscription.Status.PAST_DUE
    subscription.save(update_fields=["status", "updated_at"])
    logger.info("[billing] подписка %s: %s → past_due", subscription.pk, old_status)
    return subscription


def suspend(subscription: Subscription) -> Subscription:
    """Грейс истёк, оплаты нет → suspended (бот выключается гейтом)."""
    old_status = subscription.status
    subscription.status = Subscription.Status.SUSPENDED
    subscription.save(update_fields=["status", "updated_at"])
    logger.info("[billing] подписка %s: %s → suspended", subscription.pk, old_status)
    return subscription


def cancel(subscription: Subscription) -> Subscription:
    """Клиника ушла → canceled. Фиксируем момент отмены (canceled_at)."""
    old_status = subscription.status
    subscription.status = Subscription.Status.CANCELED
    subscription.canceled_at = timezone.now()
    subscription.save(update_fields=["status", "canceled_at", "updated_at"])
    logger.info("[billing] подписка %s: %s → canceled", subscription.pk, old_status)
    return subscription


def reset_trial(subscription: Subscription) -> Subscription:
    """Дать клинике новый пробный период (ручной сброс владельцем SaaS).

    Устанавливает status=trialing и сдвигает период на TRIAL_DAYS вперёд от now.
    Используется из admin, когда надо выдать демо-период или исправить ошибку.
    """
    now = timezone.now()
    trial_end = now + timedelta(days=settings.TRIAL_DAYS)

    old_status = subscription.status
    subscription.status = Subscription.Status.TRIALING
    subscription.current_period_start = now
    subscription.current_period_end = trial_end
    subscription.trial_end = trial_end
    subscription.canceled_at = None
    subscription.save()

    logger.info(
        "[billing] подписка %s: %s → trialing (сброс триала до %s)",
        subscription.pk, old_status, trial_end,
    )
    return subscription


# --------------------------------------------------------------------------- #
# 6-7. Учёт потребления и мягкий лимит                                         #
# --------------------------------------------------------------------------- #
def get_or_create_usage(clinic: Clinic, when: datetime | None = None) -> UsageCounter:
    """Счётчик потребления за период подписки, в который попадает `when` (или now).

    Привязка к ГРАНИЦАМ периода ПОДПИСКИ (current_period_start/end), а не к
    календарному месяцу: один счётчик на один оплаченный/пробный период.
    """
    when = when or timezone.now()

    sub = _get_subscription(clinic)
    if sub is not None and sub.current_period_start is not None:
        period_start = sub.current_period_start
        period_end = sub.current_period_end or (period_start + timedelta(days=settings.TRIAL_DAYS))
    else:
        # Подписки/периода нет — заводим минутный фолбэк-период от `when`,
        # чтобы счётчик всё же существовал (учёт не должен падать).
        period_start = when
        period_end = when + timedelta(days=settings.TRIAL_DAYS)

    usage, _ = UsageCounter.objects.get_or_create(
        clinic=clinic,
        period_start=period_start,
        defaults={"period_end": period_end},
    )
    return usage


def is_over_limit(clinic: Clinic) -> bool:
    """True, если в текущем периоде входящих сообщений больше плана message_limit.

    ВАЖНО: это МЯГКИЙ сигнал (для апселла/уведомления менеджеру), он НЕ должен сам
    отрубать бота — гейт обслуживания делает только is_clinic_serviceable().
    Безлимит (message_limit пуст) или нет подписки/тарифа → False.
    """
    sub = _get_subscription(clinic)
    if sub is None or sub.plan is None:
        return False

    limit = sub.plan.message_limit
    if limit is None:  # безлимит
        return False

    usage = get_or_create_usage(clinic)
    return usage.messages_in > limit


def subscription_status(clinic: Clinic) -> str:
    """Статус подписки клиники строкой (для логов). Нет подписки → 'none'."""
    sub = _get_subscription(clinic)
    return sub.status if sub is not None else "none"


# --------------------------------------------------------------------------- #
# 8. Инкремент счётчиков — атомарно через F() (без гонок при параллельных задачах)
# --------------------------------------------------------------------------- #
def _bump(clinic: Clinic, field: str, when: datetime | None = None) -> None:
    """+1 к указанному полю UsageCounter текущего периода атомарно (F()-выражение).

    Идемпотентность обеспечивает ВЫЗЫВАЮЩИЙ код: эти инкременты стоят в пайплайне
    ПОСЛЕ дедупликации входящего по external_id, поэтому ретрай Celery-задачи не
    доходит до них повторно для одного и того же сообщения (см. messaging/tasks.py).
    """
    usage = get_or_create_usage(clinic, when)
    UsageCounter.objects.filter(pk=usage.pk).update(**{field: F(field) + 1})


def record_incoming(clinic: Clinic, when: datetime | None = None) -> None:
    """+1 входящее сообщение."""
    _bump(clinic, "messages_in", when)


def record_ai_call(clinic: Clinic, when: datetime | None = None) -> None:
    """+1 реальный вызов Groq (генерация ответа или транскрипция)."""
    _bump(clinic, "ai_calls", when)


def record_outgoing(clinic: Clinic, when: datetime | None = None) -> None:
    """+1 отправленное ботом сообщение."""
    _bump(clinic, "messages_out", when)


def alert_over_limit_once(clinic: Clinic) -> bool:
    """Зафиксировать алерт «лимит превышен» РОВНО один раз за период.

    Если лимит превышен и в этом периоде владельцу ещё не слали алерт — пишем
    событие в BillingEventLog (unique_together не даст продублировать) и возвращаем
    True. Иначе — False. Бота НЕ отключает: это мягкий сигнал (само уведомление
    владельцу прикрутим в Промпте #5).
    """
    if not is_over_limit(clinic):
        return False

    sub = _get_subscription(clinic)
    if sub is None:
        return False

    period_anchor = sub.current_period_end or sub.current_period_start or timezone.now()
    period_key = period_anchor.isoformat()

    _, created = BillingEventLog.objects.get_or_create(
        subscription=sub,
        period_key=period_key,
        event_type=BillingEventLog.EventType.LIMIT_REACHED,
    )
    if created:
        logger.warning(
            "[billing] клиника %s превысила лимит сообщений за период (period_key=%s) "
            "— алерт владельцу (#5). Бота НЕ отключаем.",
            clinic.pk, period_key,
        )
    return created
