# Generated manually 2026-06-05 — Фаза 4: мультитенант на уровне данных.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clinics', '0002_clinic_manager_whatsapp_clinic_notifications_enabled'),
    ]

    operations = [
        migrations.AddField(
            model_name='clinic',
            name='instance_name',
            field=models.CharField(
                blank=True,
                help_text='Имя инстанса Evolution API (идентификатор подключения клиники)',
                max_length=255,
                null=True,
                unique=True,
                verbose_name='Инстанс Evolution',
            ),
        ),
        migrations.AddField(
            model_name='clinic',
            name='timezone',
            field=models.CharField(
                default='Asia/Almaty',
                help_text='IANA-таймзона клиники (например, Asia/Almaty)',
                max_length=64,
                verbose_name='Часовой пояс',
            ),
        ),
    ]
