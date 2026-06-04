"""
Модели переписки с пациентами.

Это медицинская сфера (закон РК «О персональных данных», особая категория):
контент сообщений — персональные/медицинские данные, поэтому поле `content`
ЗАШИФРОВАНО на уровне поля (django-fernet-fields-v2: значение шифруется перед
записью в БД и расшифровывается при чтении из ORM). Ключ — settings.FERNET_KEYS
(env FIELD_ENCRYPTION_KEY).

Мультитенантность: переписка привязана к клинике (`Conversation.clinic`).
"""
from __future__ import annotations

from django.db import models
from fernet_fields import EncryptedTextField


class Conversation(models.Model):
    """Диалог с одним номером пациента в рамках одной клиники."""

    class BookingStage(models.TextChoices):
        # Запись не ведётся — обычный текстовый флоу Фазы 1.
        NONE = "none", "Нет записи"
        # Бот дозапрашивает недостающие слоты (услуга/день/время).
        COLLECTING = "collecting", "Собираем данные"
        # Все нужные слоты собраны — черновик готов к передаче менеджеру (#4).
        READY = "ready", "Готово к передаче менеджеру"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        verbose_name="Клиника",
        on_delete=models.CASCADE,
        related_name="conversations",
        db_index=True,
    )

    # Номер пациента в формате E.164 (например, 77001234567).
    # По номеру ищем диалог, поэтому он НЕ шифруется (зашифрованное поле нельзя
    # индексировать и искать на стороне БД).
    customer_phone = models.CharField("Телефон пациента", max_length=32, db_index=True)

    # --- Состояние диалога записи (Фаза 3, слот-филлинг) ---
    # Стадия записи: none → collecting → ready. Хранится на диалоге, чтобы между
    # входящими сообщениями не терять, что мы уже спросили и что уже собрали.
    booking_stage = models.CharField(
        "Стадия записи",
        max_length=16,
        choices=BookingStage.choices,
        default=BookingStage.NONE,
    )
    # Черновик собранных слотов заявки. Ключи: service, preferred_date_raw,
    # preferred_time_raw, preferred_date, preferred_time, customer_name
    # (+ служебный _miss_count — счётчик нерелевантных ответов для анти-тупика).
    booking_draft = models.JSONField("Черновик заявки", default=dict, blank=True)

    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        verbose_name = "Диалог"
        verbose_name_plural = "Диалоги"
        ordering = ["-updated_at"]
        # Один диалог на пару (клиника, номер пациента).
        unique_together = ("clinic", "customer_phone")

    def __str__(self) -> str:
        return f"{self.customer_phone} @ {self.clinic_id}"


class Message(models.Model):
    """Одно сообщение в диалоге. Контент зашифрован на уровне поля."""

    class Role(models.TextChoices):
        USER = "user", "Пациент"
        ASSISTANT = "assistant", "Бот"
        SYSTEM = "system", "Система"

    conversation = models.ForeignKey(
        Conversation,
        verbose_name="Диалог",
        on_delete=models.CASCADE,
        related_name="messages",
    )

    role = models.CharField("Роль", max_length=16, choices=Role.choices)

    # ЗАШИФРОВАННОЕ поле: контент переписки (медданные). В БД хранится шифротекст.
    content = EncryptedTextField("Текст сообщения")

    # ID сообщения у WhatsApp-провайдера — для дедупликации входящих. Nullable,
    # т.к. у исходящих/системных сообщений его может не быть.
    external_id = models.CharField(
        "ID у провайдера",
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
    )

    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        verbose_name = "Сообщение"
        verbose_name_plural = "Сообщения"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"[{self.role}] {self.conversation_id} @ {self.created_at:%Y-%m-%d %H:%M}"
