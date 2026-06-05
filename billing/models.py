"""
Биллинг (Фаза 5): тарифы, подписки клиник, платежи и учёт потребления.

Бизнес-модель — месячный тариф на клинику (см. CLAUDE.md). Деньги ВСЕГДА в
DecimalField (max_digits=12, decimal_places=2) — никакого float (округления при
расчётах денег недопустимы). Все datetime — timezone-aware (проект на Asia/Almaty,
USE_TZ=True), через django.utils.timezone.now().

Мультитенантность: каждая запись биллинга привязана к клинике (`clinic_id`).
Связь Subscription↔Clinic — один-к-одному (у клиники ровно одна подписка).

Этот модуль — ТОЛЬКО модели. Пайплайн обработки сообщений и маршрутизацию он не
трогает (это следующие промпты Фазы 5).
"""
from __future__ import annotations

from django.db import models


class Plan(models.Model):
    """Тарифный план (например, «start»/«pro»). Цены правит владелец в admin."""

    # Машинный код плана — стабильный идентификатор для кода/миграций.
    code = models.CharField("Код", max_length=32, unique=True)
    name = models.CharField("Название", max_length=255)

    # Цена в тенге. Decimal — деньги, без float.
    price_kzt = models.DecimalField("Цена, ₸", max_digits=12, decimal_places=2)

    # Длительность оплаченного периода в днях (по умолчанию месяц ≈ 30 дней).
    period_days = models.PositiveIntegerField("Длительность периода, дней", default=30)

    # Лимит сообщений за период. null = безлимит.
    message_limit = models.PositiveIntegerField(
        "Лимит сообщений за период",
        null=True,
        blank=True,
        help_text="Пусто = безлимит",
    )

    # Произвольные фичи плана (флаги/квоты), например {"voice": true}.
    features = models.JSONField("Фичи", default=dict, blank=True)

    is_active = models.BooleanField("Активен", default=True)

    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        verbose_name = "Тариф"
        verbose_name_plural = "Тарифы"
        ordering = ["price_kzt"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class Subscription(models.Model):
    """Подписка клиники. У каждой клиники ровно одна (OneToOne)."""

    class Status(models.TextChoices):
        TRIALING = "trialing", "Пробный период"
        ACTIVE = "active", "Активна"
        PAST_DUE = "past_due", "Просрочена (грейс-период)"
        SUSPENDED = "suspended", "Приостановлена"
        CANCELED = "canceled", "Отменена"

    clinic = models.OneToOneField(
        "clinics.Clinic",
        verbose_name="Клиника",
        on_delete=models.CASCADE,
        related_name="subscription",
    )

    # PROTECT: нельзя удалить тариф, на котором висят подписки. null — пока триал
    # без выбранного платного тарифа.
    plan = models.ForeignKey(
        "billing.Plan",
        verbose_name="Тариф",
        on_delete=models.PROTECT,
        related_name="subscriptions",
        null=True,
        blank=True,
    )

    status = models.CharField(
        "Статус",
        max_length=16,
        choices=Status.choices,
        default=Status.TRIALING,
        db_index=True,
    )

    # Границы текущего оплаченного (или пробного) периода.
    current_period_start = models.DateTimeField(
        "Начало периода", null=True, blank=True
    )
    current_period_end = models.DateTimeField("Конец периода", null=True, blank=True)

    # Конец пробного периода.
    trial_end = models.DateTimeField("Конец пробного периода", null=True, blank=True)

    # Когда подписку отменили (если отменили).
    canceled_at = models.DateTimeField("Отменена", null=True, blank=True)

    created_at = models.DateTimeField("Создана", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлена", auto_now=True)

    class Meta:
        verbose_name = "Подписка"
        verbose_name_plural = "Подписки"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Подписка {self.clinic_id} ({self.status})"


class Payment(models.Model):
    """Платёж клиники за период. История пополнений/попыток оплаты."""

    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает оплаты"
        PAID = "paid", "Оплачен"
        FAILED = "failed", "Не прошёл"

    # PROTECT: историю платежей не теряем при попытке удалить клинику.
    clinic = models.ForeignKey(
        "clinics.Clinic",
        verbose_name="Клиника",
        on_delete=models.PROTECT,
        related_name="payments",
        db_index=True,
    )

    # SET_NULL: платёж — финансовый факт, переживает удаление подписки.
    subscription = models.ForeignKey(
        "billing.Subscription",
        verbose_name="Подписка",
        on_delete=models.SET_NULL,
        related_name="payments",
        null=True,
        blank=True,
    )

    plan = models.ForeignKey(
        "billing.Plan",
        verbose_name="Тариф",
        on_delete=models.PROTECT,
        related_name="payments",
        null=True,
        blank=True,
    )

    amount_kzt = models.DecimalField("Сумма, ₸", max_digits=12, decimal_places=2)

    # Платёжный провайдер (manual / kaspi / stripe и т.п.).
    provider = models.CharField("Провайдер", max_length=32, default="manual")

    # ID платежа на стороне провайдера — для идемпотентности и сверки.
    external_id = models.CharField(
        "ID у провайдера", max_length=255, unique=True, null=True, blank=True
    )

    status = models.CharField(
        "Статус",
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    # За какой период оплата.
    period_start = models.DateTimeField("Начало периода", null=True, blank=True)
    period_end = models.DateTimeField("Конец периода", null=True, blank=True)

    paid_at = models.DateTimeField("Оплачен", null=True, blank=True)

    created_at = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        verbose_name = "Платёж"
        verbose_name_plural = "Платежи"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Платёж {self.amount_kzt}₸ {self.clinic_id} ({self.status})"


class UsageCounter(models.Model):
    """Счётчик потребления клиники за период (сообщения и вызовы AI)."""

    # PROTECT: статистику потребления не теряем при удалении клиники.
    clinic = models.ForeignKey(
        "clinics.Clinic",
        verbose_name="Клиника",
        on_delete=models.PROTECT,
        related_name="usage_counters",
        db_index=True,
    )

    period_start = models.DateTimeField("Начало периода")
    period_end = models.DateTimeField("Конец периода")

    messages_in = models.PositiveIntegerField("Входящих сообщений", default=0)
    messages_out = models.PositiveIntegerField("Исходящих сообщений", default=0)
    ai_calls = models.PositiveIntegerField("Вызовов AI", default=0)

    class Meta:
        verbose_name = "Счётчик потребления"
        verbose_name_plural = "Счётчики потребления"
        ordering = ["-period_start"]
        # Один счётчик на (клиника, начало периода).
        unique_together = ("clinic", "period_start")

    def __str__(self) -> str:
        return f"Потребление {self.clinic_id} c {self.period_start:%Y-%m-%d}"


class BillingEventLog(models.Model):
    """Журнал биллинговых событий — защита от повторной отправки (идемпотентность).

    Например, чтобы напоминание «осталось 3 дня» ушло за период ровно один раз:
    перед отправкой пишем сюда запись; unique_together не даст продублировать.
    """

    class EventType(models.TextChoices):
        REMINDER_3D = "reminder_3d", "Напоминание за 3 дня"
        REMINDER_1D = "reminder_1d", "Напоминание за 1 день"
        EXPIRED_SUSPEND = "expired_suspend", "Приостановка по окончании"
        PERIOD_RENEWED = "period_renewed", "Период продлён"
        # Лимит сообщений за период превышен — отметка из пайплайна (мягкий сигнал,
        # бота НЕ отключает). Ставится при обработке входящего сообщения.
        LIMIT_REACHED = "limit_reached", "Лимит сообщений превышен"
        # Владелец SaaS уведомлён о превышении лимита (отдельный канал от
        # LIMIT_REACHED, чтобы пайплайн и фоновый billing-cycle не «съедали»
        # уведомление друг друга). Шлёт ежедневный run_billing_cycle, раз за период.
        OWNER_LIMIT_ALERT = "owner_limit_alert", "Владелец уведомлён о лимите"

    subscription = models.ForeignKey(
        "billing.Subscription",
        verbose_name="Подписка",
        on_delete=models.CASCADE,
        related_name="event_logs",
    )

    # Ключ периода (например, ISO-дата конца периода) — событие уникально в рамках периода.
    period_key = models.CharField("Ключ периода", max_length=64)

    event_type = models.CharField(
        "Тип события", max_length=32, choices=EventType.choices
    )

    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        verbose_name = "Событие биллинга"
        verbose_name_plural = "События биллинга"
        ordering = ["-created_at"]
        # Одно событие данного типа на (подписка, период) — защита от дублей.
        unique_together = ("subscription", "period_key", "event_type")

    def __str__(self) -> str:
        return f"{self.event_type} / {self.subscription_id} / {self.period_key}"
