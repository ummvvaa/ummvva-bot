import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("ummvva_bot")

# Все настройки с префиксом CELERY_ берём из настроек Django.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Автопоиск задач в tasks.py всех установленных приложений.
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
