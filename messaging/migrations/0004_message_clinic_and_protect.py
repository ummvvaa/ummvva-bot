# Generated manually 2026-06-05 — Фаза 4: мультитенант на уровне данных.
#
# 1) Conversation.clinic: CASCADE → PROTECT (нельзя удалить клинику, пока у неё
#    есть переписки — защита ПДн от случайного каскадного удаления).
# 2) Message получает прямой FK на клинику (денормализация для изоляции/индексации
#    горячей таблицы сообщений). Добавляем nullable → бэкфилл из conversation.clinic
#    → делаем NOT NULL. Так существующие сообщения на проде не ломаются.

import django.db.models.deletion
from django.db import migrations, models


def backfill_message_clinic(apps, schema_editor):
    Conversation = apps.get_model('messaging', 'Conversation')
    Message = apps.get_model('messaging', 'Message')
    # По диалогам: у всех его сообщений клиника = клиника диалога. Дешевле, чем
    # сохранять каждое сообщение по отдельности.
    for conv in Conversation.objects.all().iterator():
        Message.objects.filter(conversation=conv).update(clinic_id=conv.clinic_id)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('clinics', '0001_initial'),
        ('messaging', '0003_conversation_customer_name'),
    ]

    operations = [
        migrations.AlterField(
            model_name='conversation',
            name='clinic',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='conversations',
                to='clinics.clinic',
                verbose_name='Клиника',
            ),
        ),
        migrations.AddField(
            model_name='message',
            name='clinic',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='messages',
                to='clinics.clinic',
                verbose_name='Клиника',
            ),
        ),
        migrations.RunPython(backfill_message_clinic, noop_reverse),
        migrations.AlterField(
            model_name='message',
            name='clinic',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='messages',
                to='clinics.clinic',
                verbose_name='Клиника',
            ),
        ),
    ]
