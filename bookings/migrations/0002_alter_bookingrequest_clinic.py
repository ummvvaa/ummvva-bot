# Generated manually 2026-06-05 — Фаза 4: мультитенант на уровне данных.
#
# BookingRequest.clinic: CASCADE → PROTECT. Нельзя удалить клинику, пока у неё
# есть заявки (защита данных пациентов от случайного каскадного удаления).

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bookings', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='bookingrequest',
            name='clinic',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='bookings',
                to='clinics.clinic',
                verbose_name='Клиника',
            ),
        ),
    ]
