import json

from django import forms
from django.contrib import admin
from django.db import models

from .models import Clinic


class _PrettyJSONWidget(forms.Textarea):
    """Textarea, отображающий JSON с отступами для удобного редактирования."""

    def format_value(self, value):
        try:
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, indent=2)
            elif isinstance(value, str):
                value = json.dumps(json.loads(value), ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            pass
        return super().format_value(value)


@admin.register(Clinic)
class ClinicAdmin(admin.ModelAdmin):
    list_display = ("name", "whatsapp_number", "instance_name", "is_active", "updated_at")
    list_display_links = ("name",)
    list_editable = ("is_active",)
    list_filter = ("is_active",)
    search_fields = ("name", "whatsapp_number", "address", "instance_name")
    readonly_fields = ("created_at", "updated_at")
    formfield_overrides = {
        models.JSONField: {
            "widget": _PrettyJSONWidget(
                attrs={"rows": 18, "cols": 80, "style": "font-family: monospace; font-size: 13px;"}
            )
        }
    }
    fieldsets = (
        (
            "Основное",
            {"fields": ("name", "whatsapp_number", "instance_name", "timezone", "is_active")},
        ),
        (
            "Контент для бота",
            {"fields": ("services_json", "working_hours", "address", "tone", "faq")},
        ),
        (
            "Уведомления о заявках",
            {"fields": ("manager_whatsapp", "notifications_enabled")},
        ),
        ("Служебное", {"fields": ("created_at", "updated_at")}),
    )
