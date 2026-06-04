"""
Заявки на запись (Фаза 3).

ГЛАВНОЕ ПРАВИЛО ФАЗЫ 3: бот НИКОГДА не подтверждает приём сам и не пишет в чужой
календарь. Он только СОБИРАЕТ заявку и ПЕРЕДАЁТ менеджеру. Подтверждение/отказ —
всегда решение человека (менеджера клиники).

Это медицинская сфера (закон РК «О персональных данных», особая категория).
ПДн пациента (телефон, имя) шифруются на уровне поля (django-fernet-fields-v2),
как `Message.content` в Фазе 1. Услуга/дата/время — НЕ ПДн, их не шифруем
(удобно фильтровать и читать в admin).

Мультитенантность: каждая заявка привязана к клинике (`clinic_id`).
"""
from __future__ import annotations

from django.db import models
from fernet_fields import EncryptedCharField


class BookingRequest(models.Model):
    """Заявка пациента на запись. Бот её собирает, менеджер — обрабатывает."""

    class Status(models.TextChoices):
        NEW = "new", "Собрана (не отправлена менеджеру)"
        NOTIFIED = "notified", "Менеджер уведомлён"
        CONFIRMED = "confirmed", "Менеджер подтвердил"
        REJECTED = "rejected", "Отклонена / предложено другое время"
        CANCELLED = "cancelled", "Отменена пациентом"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        verbose_name="Клиника",
        on_delete=models.PROTECT,
        related_name="bookings",
        db_index=True,
    )

    # Диалог, из которого собрана заявка. SET_NULL: заявку не теряем, даже если
    # переписку удалят (например, по запросу пациента на удаление ПДн).
    conversation = models.ForeignKey(
        "messaging.Conversation",
        verbose_name="Диалог",
        on_delete=models.SET_NULL,
        related_name="bookings",
        null=True,
        blank=True,
    )

    # --- ПДн пациента: ЗАШИФРОВАНЫ на уровне поля (в БД — Fernet-токен) ---
    customer_phone = EncryptedCharField("Телефон пациента", max_length=32)
    customer_name = EncryptedCharField(
        "Имя пациента", max_length=255, null=True, blank=True
    )

    # --- Что/когда хочет пациент (НЕ ПДн, не шифруем) ---
    service = models.CharField("Услуга", max_length=255, blank=True)

    # Как пациент сказал (сырой текст) — на случай, если распарсить не вышло.
    preferred_date_raw = models.CharField(
        "Желаемая дата (как сказал)", max_length=255, blank=True
    )
    preferred_time_raw = models.CharField(
        "Желаемое время (как сказал)", max_length=255, blank=True
    )

    # Распарсенные значения, если удалось их разобрать (иначе null).
    preferred_date = models.DateField("Желаемая дата", null=True, blank=True)
    preferred_time = models.TimeField("Желаемое время", null=True, blank=True)

    status = models.CharField(
        "Статус",
        max_length=16,
        choices=Status.choices,
        default=Status.NEW,
        db_index=True,
    )

    # Что менеджер ответил/предложил (заполняется человеком при обработке).
    manager_note = models.TextField("Заметка менеджера", null=True, blank=True)

    created_at = models.DateTimeField("Создана", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлена", auto_now=True)

    class Meta:
        verbose_name = "Заявка на запись"
        verbose_name_plural = "Заявки на запись"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Заявка #{self.pk} @ {self.clinic_id} ({self.status})"
