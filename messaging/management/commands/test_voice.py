"""
Management-команда: end-to-end проверка голосового пайплайна (Фаза 2).

Тесты (все на mock-провайдерах, eager Celery, без интернета):
 1. Нормальный поток: audioMessage → download → транскрипт → ответ бота как на текст.
 2. Просроченное/недоступное медиа: download → None → _VOICE_FAIL_REPLY, диалог не создан.
 3. Очень короткое голосовое (transcribe → None) → _VOICE_FAIL_REPLY, диалог не создан.

Использование:
    docker compose exec web python manage.py test_voice
    docker compose exec web python manage.py test_voice --keep   # не чистить данные
"""
from __future__ import annotations

import json
from unittest.mock import patch

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.test import Client

from clinics.models import Clinic
from messaging.models import Conversation, Message
from messaging.tasks import _VOICE_FAIL_REPLY
from providers.ai.factory import get_ai_provider
from providers.ai.mock import MockAIProvider
from providers.whatsapp.factory import get_whatsapp_provider
from providers.whatsapp.mock import MockWhatsAppProvider

TEST_CLINIC_PHONE = "77000000888"
TEST_CUSTOMER_PHONE = "77019998888"
TEST_TOKEN = "test-voice-secret"


def _voice_payload(external_id: str, message_type: str = "audioMessage") -> dict:
    """Сгенерировать фейковый Evolution-payload для голосового сообщения."""
    return {
        "event": "messages.upsert",
        "instance": "test-instance",
        "sender": f"{TEST_CLINIC_PHONE}@s.whatsapp.net",
        "data": {
            "key": {
                "remoteJid": f"{TEST_CUSTOMER_PHONE}@s.whatsapp.net",
                "fromMe": False,
                "id": external_id,
            },
            "pushName": "Тестовый клиент",
            "message": {},
            "messageType": message_type,
        },
    }


class Command(BaseCommand):
    help = "End-to-end проверка голосового пайплайна (mock-провайдеры, eager Celery)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep",
            action="store_true",
            help="Не удалять тестовые данные после проверки.",
        )

    def _setup(self) -> None:
        settings.WHATSAPP_PROVIDER = "mock"
        settings.AI_PROVIDER = "mock"
        settings.WHATSAPP_WEBHOOK_TOKEN = TEST_TOKEN
        if "testserver" not in settings.ALLOWED_HOSTS:
            settings.ALLOWED_HOSTS.append("testserver")
        get_ai_provider.cache_clear()
        get_whatsapp_provider.cache_clear()

        from config.celery import app as celery_app

        celery_app.conf.task_always_eager = True
        celery_app.conf.task_eager_propagates = True

    def handle(self, *args, **options):
        self._setup()
        client = Client()

        clinic, created = Clinic.objects.get_or_create(
            whatsapp_number=TEST_CLINIC_PHONE,
            defaults={
                "name": "Тестовая клиника (voice)",
                "services_json": [{"name": "Чистка зубов", "price": "15 000 ₸"}],
                "is_active": True,
            },
        )

        def _clean() -> None:
            Conversation.objects.filter(
                clinic=clinic, customer_phone=TEST_CUSTOMER_PHONE
            ).delete()
            get_whatsapp_provider.cache_clear()
            get_ai_provider.cache_clear()

        _clean()
        passed = 0
        failed = 0

        # ─── Тест 1: нормальный голосовой поток ───────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING("→ Тест 1: нормальный поток (audioMessage)"))
        try:
            resp = client.post(
                "/webhook/whatsapp/",
                data=json.dumps(_voice_payload("TESTVOICE-T1")),
                content_type="application/json",
                HTTP_X_WEBHOOK_TOKEN=TEST_TOKEN,
            )
            if resp.status_code != 200:
                raise CommandError(f"Вью вернул {resp.status_code}")

            conv = Conversation.objects.filter(
                clinic=clinic, customer_phone=TEST_CUSTOMER_PHONE
            ).first()
            if conv is None:
                raise CommandError("Диалог не создан — задача не отработала.")

            msgs = list(conv.messages.order_by("created_at"))
            roles = [m.role for m in msgs]
            if roles != [Message.Role.USER, Message.Role.ASSISTANT]:
                raise CommandError(
                    f"Ожидали [user, assistant], получили {roles}."
                )

            user_msg, assistant_msg = msgs
            # Транскрипт должен стать текстом входящего сообщения.
            if "[mock-транскрипт]" not in user_msg.content:
                raise CommandError(
                    f"Транскрипт не попал в диалог: {user_msg.content!r}"
                )

            # Mock-провайдер должен был «отправить» ответ клиенту.
            wa = get_whatsapp_provider()
            sent = [s for s in getattr(wa, "sent", []) if s["to"] == TEST_CUSTOMER_PHONE]
            if not sent:
                raise CommandError("Mock-провайдер не зафиксировал отправку ответа.")
            if sent[-1]["text"] != assistant_msg.content:
                raise CommandError("Текст отправки не совпал с ответом ассистента в БД.")

            self.stdout.write(f"  транскрипт в БД:  {user_msg.content!r}")
            self.stdout.write(f"  ответ бота:       {assistant_msg.content!r}")
            self.stdout.write(self.style.SUCCESS("  ✓ Пройден"))
            passed += 1
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  ✗ ПРОВАЛЕН: {exc}"))
            failed += 1
        _clean()

        # ─── Тест 2: просроченное/недоступное медиа ───────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING("→ Тест 2: медиа недоступно (download → None)"))
        try:
            failing_wa = MockWhatsAppProvider()
            failing_wa.download_voice_media = lambda key_id: None

            with patch("messaging.tasks.get_whatsapp_provider", return_value=failing_wa):
                resp = client.post(
                    "/webhook/whatsapp/",
                    data=json.dumps(_voice_payload("TESTVOICE-T2")),
                    content_type="application/json",
                    HTTP_X_WEBHOOK_TOKEN=TEST_TOKEN,
                )
            if resp.status_code != 200:
                raise CommandError(f"Вью вернул {resp.status_code}")

            # Ранний выход из задачи — диалог создан не должен быть.
            conv = Conversation.objects.filter(
                clinic=clinic, customer_phone=TEST_CUSTOMER_PHONE
            ).first()
            if conv is not None:
                raise CommandError(
                    "Диалог создан, хотя медиа недоступно — ранний выход не сработал."
                )

            sent = [s for s in failing_wa.sent if s["to"] == TEST_CUSTOMER_PHONE]
            if not sent:
                raise CommandError("Бот не отправил ответ при недоступном медиа.")
            if sent[-1]["text"] != _VOICE_FAIL_REPLY:
                raise CommandError(
                    f"Ожидали _VOICE_FAIL_REPLY, получили {sent[-1]['text']!r}"
                )

            self.stdout.write(f"  бот ответил:      {sent[-1]['text']!r}")
            self.stdout.write(self.style.SUCCESS("  ✓ Пройден"))
            passed += 1
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  ✗ ПРОВАЛЕН: {exc}"))
            failed += 1
        _clean()

        # ─── Тест 3: транскрипция провалилась (pttMessage, transcribe → None) ─
        self.stdout.write(self.style.MIGRATE_HEADING("→ Тест 3: транскрипция провалилась (pttMessage, transcribe → None)"))
        try:
            normal_wa = MockWhatsAppProvider()
            failing_ai = MockAIProvider()
            failing_ai.transcribe = lambda audio, mime: None

            with (
                patch("messaging.tasks.get_whatsapp_provider", return_value=normal_wa),
                patch("messaging.tasks.get_ai_provider", return_value=failing_ai),
            ):
                resp = client.post(
                    "/webhook/whatsapp/",
                    data=json.dumps(_voice_payload("TESTVOICE-T3", "pttMessage")),
                    content_type="application/json",
                    HTTP_X_WEBHOOK_TOKEN=TEST_TOKEN,
                )
            if resp.status_code != 200:
                raise CommandError(f"Вью вернул {resp.status_code}")

            conv = Conversation.objects.filter(
                clinic=clinic, customer_phone=TEST_CUSTOMER_PHONE
            ).first()
            if conv is not None:
                raise CommandError(
                    "Диалог создан, хотя транскрипция провалилась — ранний выход не сработал."
                )

            sent = [s for s in normal_wa.sent if s["to"] == TEST_CUSTOMER_PHONE]
            if not sent:
                raise CommandError("Бот не отправил ответ при провале транскрипции.")
            if sent[-1]["text"] != _VOICE_FAIL_REPLY:
                raise CommandError(
                    f"Ожидали _VOICE_FAIL_REPLY, получили {sent[-1]['text']!r}"
                )

            self.stdout.write(f"  тип сообщения:    pttMessage")
            self.stdout.write(f"  бот ответил:      {sent[-1]['text']!r}")
            self.stdout.write(self.style.SUCCESS("  ✓ Пройден"))
            passed += 1
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  ✗ ПРОВАЛЕН: {exc}"))
            failed += 1
        _clean()

        if not options["keep"]:
            if created:
                clinic.delete()
            self.stdout.write("  тестовые данные удалены (--keep чтобы оставить)")

        summary = f"\n✓ Голосовой пайплайн: все {passed} теста прошли."
        if failed:
            raise CommandError(
                f"\n{failed} тест(ов) провалено, {passed} прошло."
            )
        self.stdout.write(self.style.SUCCESS(summary))
