"""
Management-команда: проверка «мозга» бота end-to-end.

Создаёт (или переиспользует) тестовую клинику с парой услуг, прогоняет
build_messages и передаёт результат в AIProvider.generate(). Печатает
системный промпт, собранный список сообщений и ответ модели.

Главная проверка: бот НЕ выдумывает цены, которых нет в данных клиники.
Для этого задаём вопрос про услугу, цены которой в services_json НЕТ
(брекеты), и смотрим, что бот не называет конкретную сумму, а предлагает
уточнить у менеджера.

Использование:
    docker compose exec web python manage.py test_brain
    docker compose exec web python manage.py test_brain --provider groq
    docker compose exec web python manage.py test_brain --keep   # не удалять тестовые данные
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

TEST_CLINIC_PHONE = "77000000001"
TEST_CUSTOMER_PHONE = "77011112233"


class Command(BaseCommand):
    help = "End-to-end проверка мозга бота: build_messages → AIProvider.generate()"

    def add_arguments(self, parser):
        parser.add_argument(
            "--provider",
            default=None,
            help="Переопределить AI_PROVIDER (mock | groq). По умолчанию — из settings.",
        )
        parser.add_argument(
            "--message",
            default="Привет! Сколько стоят брекеты и есть ли у вас отбеливание?",
            help="Новое сообщение пользователя.",
        )
        parser.add_argument(
            "--keep",
            action="store_true",
            help="Не удалять тестовую клинику и диалог после прогона.",
        )

    def handle(self, *args, **options):
        from clinics.models import Clinic
        from messaging.models import Conversation, Message
        from messaging.services import build_messages, build_system_prompt

        override = options.get("provider")
        if override:
            from django.conf import settings
            settings.AI_PROVIDER = override
            from providers.ai import factory as _fac
            _fac.get_ai_provider.cache_clear()

        from providers.ai.factory import get_ai_provider

        # --- Тестовая клиника с известными услугами и ценами ---
        clinic, _ = Clinic.objects.update_or_create(
            whatsapp_number=TEST_CLINIC_PHONE,
            defaults={
                "name": "Almaty Dental (тест)",
                "services_json": [
                    {"name": "Чистка зубов (Air Flow)", "price": "15 000 ₸"},
                    {"name": "Лечение кариеса", "price": "от 20 000 ₸"},
                    {"name": "Отбеливание", "price": "45 000 ₸"},
                ],
                "working_hours": {"Пн-Пт": "09:00–19:00", "Сб": "10:00–15:00", "Вс": "выходной"},
                "address": "г. Алматы, ул. Абая, 10",
                "tone": "Дружелюбный, на «вы», без давления.",
                "faq": [
                    {"q": "Есть ли рассрочка?", "a": "Да, рассрочка до 6 месяцев без процентов."},
                ],
            },
        )

        # --- Диалог с парой сообщений для проверки истории ---
        conversation, _ = Conversation.objects.get_or_create(
            clinic=clinic, customer_phone=TEST_CUSTOMER_PHONE
        )
        if not conversation.messages.exists():
            Message.objects.create(
                conversation=conversation, role=Message.Role.USER,
                content="Здравствуйте, вы работаете в воскресенье?",
            )
            Message.objects.create(
                conversation=conversation, role=Message.Role.ASSISTANT,
                content="Здравствуйте! В воскресенье у нас выходной, работаем Пн–Сб.",
            )

        new_text = options["message"]

        # --- Сборка контекста ---
        system_prompt = build_system_prompt(clinic)
        messages = build_messages(clinic, conversation, new_text)

        self.stdout.write(self.style.HTTP_INFO("=== СИСТЕМНЫЙ ПРОМПТ ==="))
        self.stdout.write(system_prompt + "\n")

        self.stdout.write(self.style.HTTP_INFO("=== СОБРАННЫЕ СООБЩЕНИЯ (роль → контент) ==="))
        for m in messages:
            preview = m["content"] if m["role"] != "system" else "<системный промпт выше>"
            self.stdout.write(f"  [{m['role']}] {preview}")
        self.stdout.write("")

        # --- Вызов провайдера ---
        try:
            provider = get_ai_provider()
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.HTTP_INFO(f"=== ПРОВАЙДЕР: {provider.__class__.__name__} ==="))
        self.stdout.write(f"Вопрос: {new_text}\n")

        try:
            response = provider.generate(messages, clinic)
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS("=== ОТВЕТ БОТА ==="))
        self.stdout.write(response + "\n")

        # --- Эвристическая проверка: нет выдуманной цены на брекеты ---
        # Цена отбеливания (45 000 ₸) в данных ЕСТЬ — её называть можно. Поэтому
        # ищем цену именно В ОДНОМ предложении со словом «брекет»: если бот
        # назвал сумму рядом с брекетами — это выдумка (цены брекетов в данных нет).
        self.stdout.write(self.style.HTTP_INFO("=== ПРОВЕРКА: цены на брекеты в данных НЕТ ==="))
        import re
        sentences = re.split(r"[.!?\n]+", response)
        suspicious = [
            s.strip() for s in sentences
            if "брекет" in s.lower() and re.search(r"\d[\d\s]{2,}\d", s)
        ]
        if suspicious:
            self.stdout.write(self.style.WARNING(
                "⚠️  Бот, похоже, назвал конкретную цену брекетов (которой нет в данных): "
                f"{suspicious}. Проверь ответ глазами."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                "✅ Бот не назвал конкретную цену брекетов (как и ожидалось — её нет в данных)."
            ))

        # --- Очистка тестовых данных ---
        if not options["keep"]:
            with transaction.atomic():
                conversation.delete()
                clinic.delete()
            self.stdout.write("\nТестовые данные удалены (--keep чтобы оставить).")
        else:
            self.stdout.write("\nТестовые данные оставлены (--keep).")
