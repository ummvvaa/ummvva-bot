from django.contrib import admin
from django.http import JsonResponse
from django.urls import path


def healthcheck(_request):
    """Простой health-check для деплоя/мониторинга."""
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", healthcheck, name="health"),
]
