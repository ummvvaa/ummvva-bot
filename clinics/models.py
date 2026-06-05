"""
Модель клиники — корень мультитенантности.

Один сервер обслуживает много клиник. Маршрутизация входящих WhatsApp-сообщений
идёт по номеру-получателю (`whatsapp_number`). У всех будущих таблиц с данными
клиник ОБЯЗАТЕЛЬНО будет внешний ключ на Clinic (clinic_id).

«Обучение» под клинику — это подача данных (услуги, цены, часы, адрес, FAQ, тон)
в системный промпт. Не файнтюнинг.
"""
from __future__ import annotations

from django.db import models


class Clinic(models.Model):
    name = models.CharField("Название", max_length=255)

    # Номер WhatsApp клиники в формате E.164 (например, 77001234567).
    # По нему маршрутизируются входящие сообщения — должен быть уникальным.
    whatsapp_number = models.CharField(
        "Номер WhatsApp",
        max_length=32,
        unique=True,
        help_text="Номер-получатель в формате E.164, по нему определяется клиника",
    )

    # Имя инстанса Evolution API / идентификатор WhatsApp-подключения этой клиники.
    # Уникален: две клиники не могут делить одно подключение. nullable — у старых
    # клиник до Фазы 4 его могло не быть (бэкфилл из EVOLUTION_INSTANCE в миграции).
    instance_name = models.CharField(
        "Инстанс Evolution",
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        help_text="Имя инстанса Evolution API (идентификатор подключения клиники)",
    )

    # Услуги и цены в свободной JSON-структуре, например:
    # [{"name": "Чистка", "price": "15000 ₸"}, ...]
    services_json = models.JSONField("Услуги и цены", default=list, blank=True)

    # Часы работы, например: {"mon-fri": "09:00-19:00", "sat": "10:00-15:00"}
    working_hours = models.JSONField("Часы работы", default=dict, blank=True)

    address = models.CharField("Адрес", max_length=512, blank=True)

    # Тон общения бота (например: «дружелюбный, на «вы», без давления»).
    tone = models.TextField(
        "Тон общения",
        blank=True,
        default="Дружелюбный, вежливый, на «вы». Информируем, не продаём агрессивно.",
    )

    # Часто задаваемые вопросы и ответы, например:
    # [{"q": "Есть ли рассрочка?", "a": "Да, до 6 месяцев."}, ...]
    faq = models.JSONField("FAQ", default=list, blank=True)

    # Часовой пояс клиники (IANA, например Asia/Almaty). Нужен для корректного
    # разбора «завтра/сегодня» и времени заявок относительно местного времени.
    timezone = models.CharField(
        "Часовой пояс",
        max_length=64,
        default="Asia/Almaty",
        help_text="IANA-таймзона клиники (например, Asia/Almaty)",
    )

    is_active = models.BooleanField("Активна", default=True)

    # Куда уведомлять менеджера о новых заявках на запись (Фаза 3).
    # Бот не подтверждает приём сам — он передаёт заявку на этот номер.
    manager_whatsapp = models.CharField(
        "WhatsApp менеджера",
        max_length=32,
        null=True,
        blank=True,
        help_text="Номер админа клиники (E.164) для уведомлений о заявках на запись",
    )
    notifications_enabled = models.BooleanField(
        "Уведомления о заявках включены", default=True
    )

    created_at = models.DateTimeField("Создана", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлена", auto_now=True)

    class Meta:
        verbose_name = "Клиника"
        verbose_name_plural = "Клиники"
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.whatsapp_number})"


class ClinicUser(models.Model):
    """Связь Django-пользователя с клиникой.

    Даёт менеджеру клиники доступ к Django admin в режиме read-only:
    видит только свои подписки, платежи и счётчики потребления — не чужих клиник.
    Суперадмин (владелец SaaS) не требует ClinicUser — он видит всё.
    """

    user = models.OneToOneField(
        "auth.User",
        verbose_name="Пользователь",
        on_delete=models.CASCADE,
        related_name="clinic_profile",
    )
    clinic = models.ForeignKey(
        Clinic,
        verbose_name="Клиника",
        on_delete=models.CASCADE,
        related_name="staff_users",
    )

    created_at = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        verbose_name = "Пользователь клиники"
        verbose_name_plural = "Пользователи клиник"

    def __str__(self) -> str:
        return f"{self.user} → {self.clinic}"
