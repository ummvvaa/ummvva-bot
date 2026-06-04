"""
Админка заявок на запись.

ПДн пациента (телефон, имя) шифруются в БД и расшифровываются ORM при чтении.
В СПИСКЕ заявок телефон/имя НЕ показываем (чтобы не светить ПДн пачкой) — только
в детальном просмотре, и там они readonly (расшифровка, без правки руками).
Статус и заметку менеджера можно менять (это и есть рабочий процесс обработки).

Admin-actions:
- "Подтвердить выбранные" / "Отклонить выбранные" — вызывают apply_manager_decision
  (пациент получает уведомление через Celery notify_customer). Применяются только
  к заявкам в статусе new/notified; уже закрытые (confirmed/rejected/cancelled)
  тихо пропускаются.
"""
from django.contrib import admin

from .models import BookingRequest
from .tasks import notify_customer


@admin.register(BookingRequest)
class BookingRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "clinic",
        "service",
        "preferred_date_display",
        "status",
        "created_at",
    )
    list_filter = ("clinic", "status", "created_at")
    list_display_links = ("id", "service")
    # Поиск по сырым (нешифрованным) полям — телефон/имя зашифрованы, по ним
    # искать на стороне БД нельзя.
    search_fields = ("service", "preferred_date_raw", "preferred_time_raw")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    actions = ["action_confirm_selected", "action_reject_selected"]

    # ПДн и системные поля — только для чтения (расшифровка в деталях, без правки).
    readonly_fields = (
        "clinic",
        "conversation",
        "customer_phone",
        "customer_name",
        "service",
        "preferred_date_raw",
        "preferred_time_raw",
        "preferred_date",
        "preferred_time",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        ("Клиника / диалог", {"fields": ("clinic", "conversation")}),
        ("Пациент (ПДн, зашифровано)", {"fields": ("customer_phone", "customer_name")}),
        ("Заявка", {
            "fields": (
                "service",
                ("preferred_date_raw", "preferred_time_raw"),
                ("preferred_date", "preferred_time"),
            ),
        }),
        # Менеджер работает с заявкой здесь: меняет статус и пишет заметку.
        ("Обработка менеджером", {"fields": ("status", "manager_note")}),
        ("Служебное", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="Дата / время (как сказал пациент)")
    def preferred_date_display(self, obj):
        parts = [p for p in [obj.preferred_date_raw, obj.preferred_time_raw] if p]
        return " ".join(parts) if parts else "—"

    def has_add_permission(self, request):
        # Заявки создаёт бот, не человек руками.
        return False

    # ─── Bulk actions ───────────────────────────────────────────────────────

    _OPEN_STATUSES = (BookingRequest.Status.NEW, BookingRequest.Status.NOTIFIED)
    _NOTIFY_STATUSES = (BookingRequest.Status.CONFIRMED, BookingRequest.Status.REJECTED)

    def _bulk_decision(self, request, queryset, decision: str) -> None:
        """Применить решение менеджера ко всем подходящим заявкам в queryset.

        Только new/notified → применяем; уже закрытые → пропускаем.
        """
        from .manager import apply_manager_decision

        eligible = queryset.filter(status__in=self._OPEN_STATUSES).select_related("clinic")
        count = 0
        for booking in eligible:
            apply_manager_decision(booking, decision)
            count += 1

        skipped = queryset.count() - count
        verb = "подтверждено" if decision == "confirm" else "отклонено"
        msg = f"{count} заявок {verb}."
        if skipped:
            msg += f" {skipped} пропущено (уже закрыты)."
        self.message_user(request, msg)

    @admin.action(description="✅ Подтвердить выбранные заявки (уведомить пациентов)")
    def action_confirm_selected(self, request, queryset):
        self._bulk_decision(request, queryset, "confirm")

    @admin.action(description="❌ Отклонить выбранные заявки (уведомить пациентов)")
    def action_reject_selected(self, request, queryset):
        self._bulk_decision(request, queryset, "reject")

    # ─── Путь (Б): смена статуса руками в детальном виде ───────────────────

    def save_model(self, request, obj, form, change):
        notify = (
            change
            and "status" in form.changed_data
            and obj.status in self._NOTIFY_STATUSES
        )
        super().save_model(request, obj, form, change)
        if notify:
            notify_customer.delay(obj.id)
