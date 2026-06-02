from django.contrib import admin
from django.http import JsonResponse
from django.urls import path

from messaging.views import whatsapp_webhook


def healthcheck(_request):
    """Простой health-check для деплоя/мониторинга."""
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", healthcheck, name="health"),
    # Приём входящих WhatsApp (Evolution API). Без CSRF, защита — секрет в запросе.
    path("webhook/whatsapp/", whatsapp_webhook, name="whatsapp-webhook"),
]
