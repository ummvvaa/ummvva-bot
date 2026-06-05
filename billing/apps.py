from django.apps import AppConfig


class BillingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "billing"
    verbose_name = "Биллинг"

    def ready(self) -> None:
        # Подключаем сигналы (автосоздание подписки при создании клиники).
        from . import signals  # noqa: F401
