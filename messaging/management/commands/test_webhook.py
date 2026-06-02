"""
Management-команда: end-to-end проверка склейки webhook → Celery → ответ бота.

Прогоняет фейковый payload Evolution API через реальный HTTP-вью
POST /webhook/whatsapp/ (Django test Client) при WHATSAPP_PROVIDER=mock и
AI_PROVIDER=mock, затем проверяет, что:
  • вью ответил 200;
  • в БД появился диалог и ДВА сообщения (user + assistant);
  • mock-провайдер WhatsApp «отправил» ответ клиенту.

Celery переводится в eager-режим (task_always_eager), поэтому задача
handle_incoming_message выполняется синхронно в этом же процессе — и mock-провайдер
(singleton через lru_cache) виден для проверки `.sent`.

Использование:
    docker compose exec web python manage.py test_webhook
    docker compose exec web python manage.py test_webhook --keep   # не чистить данные
"""
from __future__ import annotations

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.test import Client

from clinics.models import Clinic
from messaging.models import Conversation, Message
from providers.ai.factory import get_ai_provider
from providers.whatsapp.factory import get_whatsapp_provider

TEST_CLINIC_PHONE = "77000000777"     # наш номер клиники (получатель)
TEST_CUSTOMER_PHONE = "77019998877"   # номер клиента (отправитель)
TEST_EXTERNAL_ID = "TESTWEBHOOK-0001"
TEST_TOKEN = "test-webhook-secret"


def _fake_payload() -> dict:
    """Сымитировать payload Evolution API (событие messages.upsert)."""
    return {
        "event": "messages.upsert",
        "instance": "test-instance",
        "sender": f"{TEST_CLINIC_PHONE}@s.whatsapp.net",  # наш номер (получатель)
        "data": {
            "key": {
                "remoteJid": f"{TEST_CUSTOMER_PHONE}@s.whatsapp.net",  # клиент
                "fromMe": False,
                "id": TEST_EXTERNAL_ID,
            },
            "pushName": "Тестовый клиент",
            "message": {"conversation": "Здравствуйте! Сколько стоит чистка зубов?"},
            "messageType": "conversation",
        },
    }


class Command(BaseCommand):
    help = "End-to-end проверка webhook приёма входящих (mock-провайдеры, eager Celery)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep",
            action="store_true",
            help="Не удалять тестовую клинику и диалог после проверки.",
        )

    def handle(self, *args, **options):
        # 1. Форсируем mock-провайдеры и сбрасываем кэш фабрик (вдруг env другой).
        settings.WHATSAPP_PROVIDER = "mock"
        settings.AI_PROVIDER = "mock"
        settings.WHATSAPP_WEBHOOK_TOKEN = TEST_TOKEN
        # Django test Client ходит на host 'testserver' — разрешаем его на время теста.
        if "testserver" not in settings.ALLOWED_HOSTS:
            settings.ALLOWED_HOSTS.append("testserver")
        get_ai_provider.cache_clear()
        get_whatsapp_provider.cache_clear()

        # 2. Celery — в синхронный режим, чтобы задача выполнилась здесь же.
        from config.celery import app as celery_app

        celery_app.conf.task_always_eager = True
        celery_app.conf.task_eager_propagates = True

        # 3. Тестовая клиника (роутинг по номеру-получателю).
        clinic, created = Clinic.objects.get_or_create(
            whatsapp_number=TEST_CLINIC_PHONE,
            defaults={
                "name": "Тестовая клиника (webhook)",
                "services_json": [{"name": "Чистка зубов", "price": "15000 ₸"}],
                "is_active": True,
            },
        )
        # Чистим возможный прошлый прогон для чистоты проверки счётчиков.
        Conversation.objects.filter(
            clinic=clinic, customer_phone=TEST_CUSTOMER_PHONE
        ).delete()

        self.stdout.write(self.style.MIGRATE_HEADING("→ POST /webhook/whatsapp/"))

        # 4. Шлём payload через реальный вью.
        client = Client()
        payload = _fake_payload()
        resp = client.post(
            "/webhook/whatsapp/",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_WEBHOOK_TOKEN=TEST_TOKEN,
        )

        if resp.status_code != 200:
            raise CommandError(
                f"Ожидали 200 от вебхука, получили {resp.status_code}: {resp.content!r}"
            )
        body = resp.json()
        self.stdout.write(f"  ответ вью: {resp.status_code} {body}")
        if body.get("status") != "accepted":
            raise CommandError(f"Ожидали status=accepted, получили {body!r}")

        # 5. Проверяем БД: диалог + два сообщения.
        conversation = Conversation.objects.filter(
            clinic=clinic, customer_phone=TEST_CUSTOMER_PHONE
        ).first()
        if conversation is None:
            raise CommandError("Диалог не создан — задача не отработала.")

        msgs = list(conversation.messages.order_by("created_at"))
        roles = [m.role for m in msgs]
        self.stdout.write(f"  сообщений в БД: {len(msgs)} {roles}")

        if roles != [Message.Role.USER, Message.Role.ASSISTANT]:
            raise CommandError(
                f"Ожидали [user, assistant], получили {roles}. "
                "Проверь задачу handle_incoming_message."
            )

        user_msg, assistant_msg = msgs
        if user_msg.external_id != TEST_EXTERNAL_ID:
            raise CommandError(
                f"external_id входящего не сохранён: {user_msg.external_id!r}"
            )
        self.stdout.write(f"  user.content:      {user_msg.content!r}")
        self.stdout.write(f"  assistant.content: {assistant_msg.content!r}")

        # 6. Проверяем, что mock «отправил» ответ клиенту.
        provider = get_whatsapp_provider()
        sent = getattr(provider, "sent", [])
        sent_to_customer = [s for s in sent if s["to"] == TEST_CUSTOMER_PHONE]
        if not sent_to_customer:
            raise CommandError(
                "Mock-провайдер не зафиксировал отправку ответа клиенту."
            )
        last = sent_to_customer[-1]
        self.stdout.write(
            f"  mock отправил → {last['to']}: {last['text']!r} (id={last['message_id']})"
        )
        if last["text"] != assistant_msg.content:
            raise CommandError(
                "Текст отправленного сообщения не совпал с ответом ассистента в БД."
            )

        # 7. Доп. проверка дедупликации: повторный тот же payload не создаёт дублей.
        resp2 = client.post(
            "/webhook/whatsapp/",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_WEBHOOK_TOKEN=TEST_TOKEN,
        )
        count_after = conversation.messages.filter(
            role=Message.Role.USER, external_id=TEST_EXTERNAL_ID
        ).count()
        if resp2.status_code != 200 or count_after != 1:
            raise CommandError(
                f"Дедупликация не сработала: повтор дал {count_after} входящих "
                f"(ожидали 1), код {resp2.status_code}."
            )
        self.stdout.write("  дедупликация повторного входящего: OK")

        # 8. Проверка секрета: без токена — 403.
        resp_forbidden = client.post(
            "/webhook/whatsapp/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        if resp_forbidden.status_code != 403:
            raise CommandError(
                f"Без секрета ожидали 403, получили {resp_forbidden.status_code}."
            )
        self.stdout.write("  отказ без секрета: 403 OK")

        # Чистка.
        if not options["keep"]:
            conversation.delete()
            if created:
                clinic.delete()
            self.stdout.write("  тестовые данные удалены (--keep чтобы оставить)")

        self.stdout.write(self.style.SUCCESS("\n✓ Webhook end-to-end: всё прошло."))
