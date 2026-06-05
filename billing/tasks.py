"""
Celery-задачи биллинга (Фаза 5, Промпт #5).

Главная — `run_billing_cycle`: ежедневная фоновая проверка ВСЕХ подписок
(запускается из beat-расписания, см. `config/settings.py::CELERY_BEAT_SCHEDULE`).

Все действия ИДЕМПОТЕНТНЫ: за один период каждое событие срабатывает ровно один
раз. Дедупликация — через `BillingEventLog(subscription, period_key, event_type)`
(unique_together), тем же приёмом, что уже используется в
`services.alert_over_limit_once`. `period_key` строится от конца текущего периода —
после продления/оплаты ключ меняется, и события нового периода считаются заново.

Переходы статусов делаются ТОЛЬКО через сервисный слой (`services.mark_past_due` /
`services.suspend`) — единый источник истины. Отправка сообщений — через ту же
абстракцию WhatsApp-провайдера, что и Фаза 3; в mock-режиме они просто логируются,
поэтому задача полностью работает офлайн.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from billing import services
from billing.models import BillingEventLog, Subscription
from providers.whatsapp.factory import get_whatsapp_provider_for_clinic

logger = logging.getLogger(__name__)

# Пороги напоминаний об оплате (в днях до конца периода).
REMIND_3D_DAYS = 3
REMIND_1D_DAYS = 1

# Шаблоны сообщений — нейтральные, без давления (см. ТЗ).
MSG_REMINDER_3D = (
    "Здравствуйте! Напоминаем: подписка на WhatsApp-ассистента для клиники «{clinic}» "
    "заканчивается через 3 дня. Чтобы сервис продолжил работать без перерыва, "
    "продлите её заранее."
)
MSG_REMINDER_1D = (
    "Здравствуйте! Подписка на WhatsApp-ассистента для клиники «{clinic}» "
    "заканчивается завтра. Напоминаем о продлении, чтобы бот оставался на связи."
)
MSG_SUSPENDED = (
    "Сервис WhatsApp-ассистента для клиники «{clinic}» приостановлен до оплаты. "
    "После продления он снова заработает. Если нужна помощь — ответьте на это сообщение."
)
MSG_OWNER_OVER_LIMIT = (
    "ℹ️ Клиника «{clinic}» (id={clinic_id}) превысила лимит сообщений по тарифу "
    "за текущий период. Бот продолжает работать. Возможно, стоит предложить апгрейд."
)

_REMINDER_STATUSES = (Subscription.Status.TRIALING, Subscription.Status.ACTIVE)


def _period_key(subscription: Subscription) -> str | None:
    """Уникальный ключ периода для дедупликации событий.

    Формат: f"{subscription_id}:{current_period_end:%Y-%m-%d}". Привязан к концу
    периода — после продления/оплаты конец сдвигается, ключ меняется, и события
    нового периода считаются заново. Без периода вернёт None (нечего считать).
    """
    end = subscription.current_period_end
    if end is None:
        return None
    return f"{subscription.pk}:{end:%Y-%m-%d}"


def _send(clinic, to: str | None, text: str) -> bool:
    """Отправить служебное сообщение через WhatsApp-провайдер клиники.

    В mock-режиме просто логируется (офлайн). Любые ошибки гасим и логируем —
    billing-cycle не должен падать из-за одной неуспешной отправки.
    """
    if not to:
        return False
    try:
        wa = get_whatsapp_provider_for_clinic(clinic)
        result = wa.send_message(to, text)
        return bool(getattr(result, "success", False))
    except Exception as exc:  # сеть/провайдер — не роняем цикл
        logger.warning(
            "[billing-cycle] не удалось отправить сообщение (clinic=%s): %s",
            getattr(clinic, "pk", None), type(exc).__name__,
        )
        return False


def _event_once(subscription: Subscription, period_key: str, event_type: str) -> bool:
    """Зарезервировать событие за период РОВНО один раз (идемпотентность).

    get_or_create по (subscription, period_key, event_type): unique_together не даст
    дубль. Возвращает True, только если событие создано впервые в этом периоде —
    значит, соответствующее действие (рассылку) надо выполнить.
    """
    _, created = BillingEventLog.objects.get_or_create(
        subscription=subscription,
        period_key=period_key,
        event_type=event_type,
    )
    return created


def _process_reminders(sub: Subscription, period_key: str, days_left: int) -> None:
    """Напоминания об оплате за 3 и за 1 день (каждое — один раз за период)."""
    if sub.status not in _REMINDER_STATUSES:
        return

    clinic = sub.clinic

    # Резервируем событие ДО отправки (как alert_over_limit_once): гарантирует
    # «ровно один раз» даже при ретраях. Порог «<=» делает напоминание устойчивым
    # к пропущенному дню beat (если день T-3 пропущен, оно уйдёт на T-2).
    if days_left <= REMIND_3D_DAYS:
        if _event_once(sub, period_key, BillingEventLog.EventType.REMINDER_3D):
            _send(clinic, clinic.manager_whatsapp, MSG_REMINDER_3D.format(clinic=clinic.name))
            logger.info("[billing-cycle] напоминание T-3 отправлено (sub=%s)", sub.pk)

    if days_left <= REMIND_1D_DAYS:
        if _event_once(sub, period_key, BillingEventLog.EventType.REMINDER_1D):
            _send(clinic, clinic.manager_whatsapp, MSG_REMINDER_1D.format(clinic=clinic.name))
            logger.info("[billing-cycle] напоминание T-1 отправлено (sub=%s)", sub.pk)


def _process_over_limit(sub: Subscription, period_key: str) -> None:
    """Мягкое уведомление владельца SaaS о превышении лимита (раз за период).

    Бота НЕ трогаем. Отдельный event_type (OWNER_LIMIT_ALERT), чтобы пайплайнный
    LIMIT_REACHED и этот алерт не «съедали» друг друга. Если OWNER_WHATSAPP пуст —
    остаётся только лог.
    """
    if not services.is_over_limit(sub.clinic):
        return
    if not _event_once(sub, period_key, BillingEventLog.EventType.OWNER_LIMIT_ALERT):
        return

    clinic = sub.clinic
    logger.warning(
        "[billing-cycle] клиника %s превысила лимит сообщений за период (period_key=%s)",
        clinic.pk, period_key,
    )
    if settings.OWNER_WHATSAPP:
        _send(
            clinic,
            settings.OWNER_WHATSAPP,
            MSG_OWNER_OVER_LIMIT.format(clinic=clinic.name, clinic_id=clinic.pk),
        )


def _process_subscription(sub: Subscription, now) -> None:
    """Обработать одну подписку за текущий прогон цикла."""
    period_key = _period_key(sub)
    if period_key is None:
        return

    period_end = sub.current_period_end
    grace_deadline = period_end + timedelta(days=settings.GRACE_DAYS)

    # 5. Мягкий сигнал о лимите — независимо от стадии периода.
    _process_over_limit(sub, period_key)

    if now < period_end:
        # Период ещё идёт → напоминания об оплате (T-3 / T-1).
        days_left = (period_end - now).days
        _process_reminders(sub, period_key, days_left)
        return

    # 3. Период кончился, оплаты нет → past_due (бот ещё работает в грейсе).
    if sub.status in _REMINDER_STATUSES:
        services.mark_past_due(sub)

    # 4. Грейс истёк, всё ещё не оплачено → suspend + уведомление (раз за период).
    if now > grace_deadline and sub.status == Subscription.Status.PAST_DUE:
        services.suspend(sub)
        clinic = sub.clinic
        if _event_once(sub, period_key, BillingEventLog.EventType.EXPIRED_SUSPEND):
            _send(clinic, clinic.manager_whatsapp, MSG_SUSPENDED.format(clinic=clinic.name))
            logger.info("[billing-cycle] клиника %s приостановлена (sub=%s)", clinic.pk, sub.pk)


@shared_task(ignore_result=True)
def run_billing_cycle() -> dict:
    """Ежедневная проверка всех подписок (beat, 09:00 Asia/Almaty).

    Идемпотентна: повторный прогон в тот же период не дублирует ни рассылок, ни
    суспендов (защита — BillingEventLog). Одна сбойная подписка не валит весь цикл.
    Возвращает короткую сводку (для логов/отладки).
    """
    now = timezone.now()
    processed = 0
    errors = 0

    qs = Subscription.objects.select_related("clinic", "plan")
    for sub in qs:
        try:
            _process_subscription(sub, now)
            processed += 1
        except Exception as exc:  # одна подписка не должна валить весь прогон
            errors += 1
            logger.exception(
                "[billing-cycle] ошибка обработки подписки %s: %s",
                sub.pk, type(exc).__name__,
            )

    logger.info("[billing-cycle] завершён: обработано=%s, ошибок=%s", processed, errors)
    return {"processed": processed, "errors": errors}
