# Generated manually 2026-06-05 — Фаза 4: бэкфилл инстанса из single-clinic .env.
#
# До Фазы 4 продукт работал на одну клинику, имя инстанса Evolution жило в env
# EVOLUTION_INSTANCE. Эта data-миграция привязывает это значение к уже
# существующей единственной клинике, чтобы маршрутизация по инстансу не сломалась
# на проде. Если клиник несколько (или ноль), или env пуст — ничего не делаем
# (instance_name уникален; вешать один и тот же инстанс на разные клиники нельзя).

import os

from django.db import migrations


def backfill_instance_name(apps, schema_editor):
    Clinic = apps.get_model('clinics', 'Clinic')
    instance = (os.environ.get('EVOLUTION_INSTANCE') or '').strip()
    if not instance:
        return

    clinics = list(Clinic.objects.all()[:2])
    # Бэкфилл только для однозначного single-clinic случая.
    if len(clinics) != 1:
        return

    clinic = clinics[0]
    if clinic.instance_name:
        return
    # Не перетираем, если кто-то уже занял это имя инстанса.
    if Clinic.objects.filter(instance_name=instance).exists():
        return

    clinic.instance_name = instance
    clinic.save(update_fields=['instance_name'])


def noop_reverse(apps, schema_editor):
    # Откат не трогаем: instance_name снова станет неважен, поле удалит обратная
    # schema-миграция. Данные не разрушаем.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('clinics', '0003_clinic_instance_name_clinic_timezone'),
    ]

    operations = [
        migrations.RunPython(backfill_instance_name, noop_reverse),
    ]
