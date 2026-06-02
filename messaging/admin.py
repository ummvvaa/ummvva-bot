"""
Админка переписки.

Переписка пациентов — медданные. В админке только просмотр (без ручного
создания/редактирования): списки read-only, контент сообщения НЕ показываем в
списке (чтобы не расшифровывать пачкой) — только в детальном просмотре.
"""
from django.contrib import admin

from .models import Conversation, Message


class _ReadOnlyAdmin(admin.ModelAdmin):
    """Базовый просмотр-только админ для медданных переписки."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        # Разрешаем заходить в детальный просмотр, но без сохранения (все поля
        # readonly), поэтому фактически это view-only.
        return False


class MessageInline(admin.StackedInline):
    """Инлайн сообщений — только в детальном просмотре диалога.

    Контент (зашифрованный в БД) расшифровывается ORM при чтении и виден здесь.
    В списке диалогов контент НЕ показывается — только метаданные.
    """

    model = Message
    extra = 0
    can_delete = False
    fields = ("role", "content", "external_id", "created_at")
    readonly_fields = ("role", "content", "external_id", "created_at")
    ordering = ("created_at",)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Conversation)
class ConversationAdmin(_ReadOnlyAdmin):
    list_display = ("id", "clinic", "customer_phone", "created_at", "updated_at", "message_count")
    list_filter = ("clinic",)
    search_fields = ("customer_phone",)
    readonly_fields = ("clinic", "customer_phone", "created_at", "updated_at")
    inlines = (MessageInline,)

    @admin.display(description="Сообщений")
    def message_count(self, obj):
        return obj.messages.count()


@admin.register(Message)
class MessageAdmin(_ReadOnlyAdmin):
    # В списке контента нет — только метаданные (без расшифровки).
    list_display = ("id", "conversation", "role", "external_id", "created_at")
    list_filter = ("role", "conversation__clinic")
    search_fields = ("external_id",)
    # content — в детальном просмотре (расшифровывается ORM-ом при чтении).
    readonly_fields = ("conversation", "role", "content", "external_id", "created_at")
