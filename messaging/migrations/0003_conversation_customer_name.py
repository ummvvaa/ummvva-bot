# Generated manually 2026-06-04

import fernet_fields.fields
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('messaging', '0002_conversation_booking_draft_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='conversation',
            name='customer_name',
            field=fernet_fields.fields.EncryptedCharField(
                blank=True, max_length=128, null=True, verbose_name='Имя пациента'
            ),
        ),
    ]
