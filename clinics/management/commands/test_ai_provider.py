"""
Management-команда: вызывает AI-провайдер с тестовым промптом и печатает ответ.

Использование:
    docker compose exec web python manage.py test_ai_provider
    docker compose exec web python manage.py test_ai_provider --provider groq
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Тест AI-провайдера: generate на тестовый промпт"

    def add_arguments(self, parser):
        parser.add_argument(
            "--provider",
            default=None,
            help="Переопределить AI_PROVIDER (mock | groq). По умолчанию — из settings.",
        )

    def handle(self, *args, **options):
        override = options.get("provider")
        if override:
            from django.conf import settings
            settings.AI_PROVIDER = override
            # Сбрасываем lru_cache, чтобы фабрика пересоздала провайдер.
            from providers.ai import factory as _fac
            _fac.get_ai_provider.cache_clear()

        from providers.ai.factory import get_ai_provider

        try:
            provider = get_ai_provider()
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"Провайдер: {provider.__class__.__name__}\n")

        class FakeClinic:
            name = "Тестовая клиника (Almaty Dental)"

        messages = [
            {
                "role": "system",
                "content": (
                    "Ты вежливый ассистент стоматологии «Almaty Dental». "
                    "Кратко рассказывай об услугах: лечение кариеса, имплантация, "
                    "отбеливание, протезирование. Отвечай по-русски, 2-3 предложения."
                ),
            },
            {"role": "user", "content": "Привет, какие услуги есть?"},
        ]

        self.stdout.write("Запрос к провайдеру...\n")
        try:
            response = provider.generate(messages, FakeClinic())
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"\nОтвет:\n{response}\n")
