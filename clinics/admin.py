from django.contrib import admin

from .models import Clinic


@admin.register(Clinic)
class ClinicAdmin(admin.ModelAdmin):
    list_display = ("name", "whatsapp_number", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "whatsapp_number", "address")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Основное", {"fields": ("name", "whatsapp_number", "is_active")}),
        ("Контент для бота", {
            "fields": ("services_json", "working_hours", "address", "tone", "faq"),
        }),
        ("Уведомления о заявках", {
            "fields": ("manager_whatsapp", "notifications_enabled"),
        }),
        ("Служебное", {"fields": ("created_at", "updated_at")}),
    )
