"""
Admin биллинга.

Два режима доступа:
  • Суперадмин (владелец SaaS) — видит все клиники, управляет тарифами,
    запускает actions (продление/активация/триал/суспенд), подтверждает платежи.
  • Менеджер клиники (ClinicUser) — readonly-кабинет ТОЛЬКО своей клиники:
    текущая подписка, история платежей, счётчики потребления. Actions недоступны.

Изоляция: get_queryset фильтрует по clinic для не-суперадминов — тот же механизм
clinic_id FK, что на всех доменных таблицах Фазы 4. Смена статусов подписки —
ТОЛЬКО через billing.services, никаких прямых .status= в admin.
"""
from __future__ import annotations

import logging

from django.contrib import admin, messages
from django.utils import timezone

from billing import services
from billing.models import BillingEventLog, Payment, Plan, Subscription, UsageCounter
from providers.billing.factory import get_billing_provider

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Скоупинг: определяем клинику текущего пользователя                          #
# --------------------------------------------------------------------------- #

def _clinic_for_user(user):
    """Клиника текущего пользователя или None (суперадмин видит всё).

    None означает «не фильтровать» (суперадмин). Если ClinicUser не найден —
    пользователь не привязан к клинике (показывается пустой список).
    """
    if user.is_superuser:
        return None
    try:
        return user.clinic_profile.clinic
    except Exception:
        return False  # не суперадмин и без клиники → пустой qs


class _ClinicScopedMixin:
    """Примесь: скоупинг queryset по clinic для не-суперадминов."""

    _clinic_filter_field = "clinic"  # поле FK на Clinic (переопределить при нужде)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        clinic = _clinic_for_user(request.user)
        if clinic is None:
            return qs  # суперадмин
        if clinic is False:
            return qs.none()  # пользователь без привязки
        return qs.filter(**{self._clinic_filter_field: clinic})

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            actions.clear()
        return actions

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


# --------------------------------------------------------------------------- #
# PlanAdmin — только суперадмин                                                #
# --------------------------------------------------------------------------- #

@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    """Управление тарифами: цены, лимиты, фичи. Доступно только владельцу SaaS."""

    list_display = ("name", "code", "price_kzt", "period_days", "message_limit", "is_active")
    list_editable = ("price_kzt", "is_active")
    list_display_links = ("name",)
    search_fields = ("code", "name")
    list_filter = ("is_active",)

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


# --------------------------------------------------------------------------- #
# SubscriptionAdmin — суперадмин: full control; клиника: read-only             #
# --------------------------------------------------------------------------- #

@admin.register(Subscription)
class SubscriptionAdmin(_ClinicScopedMixin, admin.ModelAdmin):
    """Подписки клиник.

    Суперадмин: список с actions (продлить/активировать/триал/суспенд).
    Менеджер клиники: read-only панель своей подписки (без actions).
    """

    list_display = (
        "clinic",
        "plan",
        "status",
        "current_period_end",
        "days_remaining",
        "usage_messages_in",
    )
    list_filter = ("status", "plan")
    search_fields = ("clinic__name",)
    autocomplete_fields = ("clinic", "plan")
    readonly_fields = ("created_at", "updated_at")
    actions = ["action_renew", "action_activate_pro", "action_to_trial", "action_suspend"]

    # --- вычисляемые колонки ---

    @admin.display(description="До конца, дн.")
    def days_remaining(self, obj):
        if obj.current_period_end is None:
            return "—"
        delta = obj.current_period_end - timezone.now()
        days = delta.days
        if days < 0:
            return f"просрочено {-days} дн."
        return f"{days} дн."

    @admin.display(description="Входящих (период)")
    def usage_messages_in(self, obj):
        try:
            usage = services.get_or_create_usage(obj.clinic)
        except Exception:
            return "—"
        limit = obj.plan.message_limit if obj.plan else None
        if limit is not None:
            return f"{usage.messages_in} / {limit}"
        return f"{usage.messages_in}"

    # --- actions (только суперадмин, get_actions зачищает для остальных) ---

    @admin.action(description="Продлить на 1 месяц")
    def action_renew(self, request, queryset):
        count, errors = 0, 0
        for sub in queryset.select_related("clinic", "plan"):
            try:
                services.renew(sub)
                count += 1
            except ValueError as exc:
                errors += 1
                logger.warning("[billing/admin] renew sub #%s: %s", sub.pk, exc)
        if count:
            self.message_user(request, f"Продлено: {count} подп.", messages.SUCCESS)
        if errors:
            self.message_user(
                request,
                f"Пропущено (нет тарифа): {errors} подп.",
                messages.WARNING,
            )

    @admin.action(description="Активировать на тарифе Pro")
    def action_activate_pro(self, request, queryset):
        try:
            pro_plan = Plan.objects.get(code="pro")
        except Plan.DoesNotExist:
            self.message_user(request, "Тариф «pro» не найден в БД.", messages.ERROR)
            return
        count = 0
        for sub in queryset.select_related("clinic"):
            services.activate(sub, plan=pro_plan)
            count += 1
        self.message_user(
            request, f"Активировано на тарифе Pro: {count} подп.", messages.SUCCESS
        )

    @admin.action(description="Перевести в триал")
    def action_to_trial(self, request, queryset):
        count = 0
        for sub in queryset.select_related("clinic"):
            services.reset_trial(sub)
            count += 1
        self.message_user(
            request, f"Переведено в пробный период: {count} подп.", messages.SUCCESS
        )

    @admin.action(description="Приостановить")
    def action_suspend(self, request, queryset):
        count = 0
        for sub in queryset.select_related("clinic"):
            services.suspend(sub)
            count += 1
        self.message_user(
            request, f"Приостановлено: {count} подп.", messages.SUCCESS
        )


# --------------------------------------------------------------------------- #
# PaymentAdmin — суперадмин: подтверждение платежей; клиника: история (ro)    #
# --------------------------------------------------------------------------- #

@admin.register(Payment)
class PaymentAdmin(_ClinicScopedMixin, admin.ModelAdmin):
    """Платежи клиник.

    Суперадмин: action «Подтвердить оплату» → вызывает BillingProvider.confirm_payment.
    После оплаты external_id и сумма становятся readonly (финансовый факт).
    Менеджер клиники: видит только историю платежей своей клиники (read-only).
    """

    list_display = (
        "clinic",
        "amount_kzt",
        "provider",
        "status",
        "paid_at",
        "created_at",
    )
    list_filter = ("status", "provider")
    search_fields = ("clinic__name", "external_id")
    readonly_fields = ("created_at",)
    actions = ["action_confirm_payment"]

    def get_readonly_fields(self, request, obj=None):
        base = list(super().get_readonly_fields(request, obj))
        if obj and obj.status == Payment.Status.PAID:
            for field in ("external_id", "amount_kzt"):
                if field not in base:
                    base.append(field)
        return base

    @admin.action(description="Подтвердить оплату")
    def action_confirm_payment(self, request, queryset):
        provider = get_billing_provider()
        count, skipped = 0, 0
        for payment in queryset.select_related("clinic", "subscription", "plan"):
            if payment.status == Payment.Status.PAID:
                skipped += 1
                continue
            try:
                provider.confirm_payment(payment)
                count += 1
            except Exception as exc:
                logger.exception(
                    "[billing/admin] confirm_payment #%s failed: %s", payment.pk, exc
                )
        if count:
            self.message_user(
                request, f"Подтверждено: {count} платежей.", messages.SUCCESS
            )
        if skipped:
            self.message_user(
                request,
                f"Пропущено (уже оплачены): {skipped}.",
                messages.WARNING,
            )


# --------------------------------------------------------------------------- #
# UsageCounterAdmin — read-only аналитика; клиника видит свои счётчики        #
# --------------------------------------------------------------------------- #

@admin.register(UsageCounter)
class UsageCounterAdmin(_ClinicScopedMixin, admin.ModelAdmin):
    """Счётчики потребления. Только просмотр (аналитика / апселл).

    Суперадмин видит все клиники. Менеджер клиники — только свой счётчик.
    """

    list_display = (
        "clinic",
        "period_start",
        "period_end",
        "messages_in",
        "messages_out",
        "ai_calls",
    )
    list_filter = ("clinic",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


# --------------------------------------------------------------------------- #
# BillingEventLogAdmin — только суперадмин (внутренняя аналитика)             #
# --------------------------------------------------------------------------- #

@admin.register(BillingEventLog)
class BillingEventLogAdmin(admin.ModelAdmin):
    """Журнал биллинговых событий. Только суперадмин (внутренняя аналитика)."""

    list_display = ("subscription", "event_type", "period_key", "created_at")
    list_filter = ("event_type",)
    readonly_fields = ("created_at",)

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
