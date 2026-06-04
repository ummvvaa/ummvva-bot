"""
Management-команда: E2E-доказательство изоляции данных между клиниками (Фаза 4).

Прогоняет весь путь обработки сообщения для ДВУХ клиник ПАРАЛЛЕЛЬНО (один и тот
же пациентский номер пишет в обе) и печатает PASS/FAIL по каждому пункту изоляции.
Полностью офлайн: mock-провайдеры WhatsApp/AI, eager Celery, без ключей и сети.

Проверяемые пункты (зеркало pytest-набора messaging/test_isolation.py):
  1. Маршрутизация: входящее в А → контекст А, в Б → контекст Б; неизвестный
     номер не создаёт записей и не падает.
  2. Системный промпт А не содержит услуг/цен/FAQ клиники Б (проверка строкой).
  3. История: один номер в А и Б = две независимые беседы; история А не отдаёт
     сообщения Б.
  4. Заявки: booking А не виден в выборке Б; уведомление ушло только менеджеру А.
  5. Прямой запрос с фильтром clinic_id=А не возвращает ни строки Б.

Использование:
    docker compose exec web python manage.py test_multitenant_flow
    docker compose exec web python manage.py test_multitenant_flow --keep
"""
from __future__ import annotations

from unittest.mock import patch

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from bookings.models import BookingRequest
from bookings.tasks import notify_manager
from clinics.models import Clinic
from messaging.models import Conversation, Message
from messaging.services import build_messages
from messaging.services.prompt import build_system_prompt
from messaging.services.conversation import get_history
from providers.ai.factory import get_ai_provider
from providers.ai.mock import MockAIProvider
from providers.whatsapp.factory import get_whatsapp_provider
from providers.whatsapp.mock import MockWhatsAppProvider

# Один пациентский номер пишет в обе клиники — главный провокатор утечки.
CUSTOMER_PHONE = "77000007777"

A_NUMBER = "77000001001"
A_INSTANCE = "mt-clinic-a"
A_MANAGER = "77000001002"

B_NUMBER = "77000002001"
B_INSTANCE = "mt-clinic-b"
B_MANAGER = "77000002002"

UNKNOWN_NUMBER = "79990000000"


class Command(BaseCommand):
    help = "E2E-доказательство изоляции данных двух клиник (mock, eager Celery, офлайн)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep",
            action="store_true",
            help="Не удалять тестовые данные после прогона.",
        )

    # --- утилиты вывода --------------------------------------------------
    def _check(self, condition: bool, label: str) -> bool:
        if condition:
            self.stdout.write(self.style.SUCCESS(f"  PASS  {label}"))
        else:
            self.stdout.write(self.style.ERROR(f"  FAIL  {label}"))
        return bool(condition)

    def _setup(self) -> None:
        settings.WHATSAPP_PROVIDER = "mock"
        settings.AI_PROVIDER = "mock"
        get_ai_provider.cache_clear()
        get_whatsapp_provider.cache_clear()
        from config.celery import app as celery_app

        celery_app.conf.task_always_eager = True
        celery_app.conf.task_eager_propagates = True

    def _provider(self):
        """Один общий mock-провайдер: ловим ВСЕ исходящие, чтобы видеть утечки адресатов."""
        return MockWhatsAppProvider()

    def _send(self, provider, **kwargs) -> None:
        from messaging.tasks import handle_incoming_message

        with (
            patch("messaging.tasks.get_ai_provider", return_value=MockAIProvider()),
            patch(
                "messaging.tasks.get_whatsapp_provider_for_clinic",
                return_value=provider,
            ),
        ):
            handle_incoming_message(**kwargs)

    # --- основной сценарий ----------------------------------------------
    def handle(self, *args, **options):
        self._setup()
        self._cleanup()

        clinic_a = Clinic.objects.create(
            name="MT-Клиника-А",
            whatsapp_number=A_NUMBER,
            instance_name=A_INSTANCE,
            manager_whatsapp=A_MANAGER,
            notifications_enabled=True,
            services_json=[{"name": "Чистка-А-уникальная", "price": "11 111 ₸"}],
            working_hours={"Пн-Пт": "09:00-18:00 (А)"},
            faq=[{"q": "Рассрочка в А?", "a": "рассрочка-А Kaspi."}],
            address="Адрес-А, Алматы",
        )
        clinic_b = Clinic.objects.create(
            name="MT-Клиника-Б",
            whatsapp_number=B_NUMBER,
            instance_name=B_INSTANCE,
            manager_whatsapp=B_MANAGER,
            notifications_enabled=True,
            services_json=[{"name": "Имплант-Б-уникальный", "price": "222 222 ₸"}],
            working_hours={"Сб-Вс": "10:00-16:00 (Б)"},
            faq=[{"q": "Наркоз в Б?", "a": "седация-Б доступна."}],
            address="Адрес-Б, Астана",
        )

        passed = 0
        failed = 0

        def tally(ok: bool) -> None:
            nonlocal passed, failed
            passed += ok
            failed += not ok

        provider = self._provider()

        # ── Параллельный прогон: один номер пишет в ОБЕ клиники ──────────
        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n═══ Прогон: пациент пишет в обе клиники + неизвестный номер ═══"
        ))
        self._send(
            provider,
            clinic_number=A_NUMBER, instance_name=A_INSTANCE,
            customer_phone=CUSTOMER_PHONE,
            text="сколько стоит чистка в клинику А?", external_id="mt-a-1",
        )
        self._send(
            provider,
            clinic_number=B_NUMBER, instance_name=B_INSTANCE,
            customer_phone=CUSTOMER_PHONE,
            text="сколько стоит имплант в клинику Б?", external_id="mt-b-1",
        )
        # Неизвестный номер — не должен ничего создать и не упасть.
        before_conv = Conversation.objects.count()
        self._send(
            provider,
            clinic_number=UNKNOWN_NUMBER, instance_name="nope",
            customer_phone=CUSTOMER_PHONE,
            text="привет неизвестной клинике", external_id="mt-unknown-1",
        )

        conv_a = Conversation.objects.filter(clinic=clinic_a, customer_phone=CUSTOMER_PHONE).first()
        conv_b = Conversation.objects.filter(clinic=clinic_b, customer_phone=CUSTOMER_PHONE).first()

        # ── Пункт 1: маршрутизация ──────────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING("\n1. Маршрутизация"))
        tally(self._check(conv_a is not None, "Сообщение в А создало диалог в клинике А"))
        tally(self._check(conv_b is not None, "Сообщение в Б создало диалог в клинике Б"))
        tally(self._check(
            conv_a is not None and conv_b is not None and conv_a.pk != conv_b.pk,
            "Диалоги А и Б — разные записи",
        ))
        tally(self._check(
            Conversation.objects.count() == before_conv,
            "Неизвестный номер не создал ни одного диалога",
        ))
        tally(self._check(
            not Message.objects.filter(clinic__whatsapp_number=UNKNOWN_NUMBER).exists(),
            "Неизвестный номер не создал ни одного сообщения (и не упал)",
        ))

        # ── Пункт 2: системный промпт ───────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING("\n2. Системный промпт"))
        prompt_a = build_system_prompt(clinic_a)
        prompt_b = build_system_prompt(clinic_b)
        b_markers = ["Имплант-Б-уникальный", "222 222 ₸", "седация-Б", clinic_b.name, "Адрес-Б"]
        a_markers = ["Чистка-А-уникальная", "11 111 ₸", "рассрочка-А", clinic_a.name, "Адрес-А"]
        tally(self._check("Чистка-А-уникальная" in prompt_a, "Промпт А содержит свою услугу/цену"))
        leaks_b = [m for m in b_markers if m in prompt_a]
        tally(self._check(not leaks_b, f"Промпт А не содержит данных Б (утечки: {leaks_b or 'нет'})"))
        leaks_a = [m for m in a_markers if m in prompt_b]
        tally(self._check(not leaks_a, f"Промпт Б не содержит данных А (утечки: {leaks_a or 'нет'})"))

        # ── Пункт 3: история диалога ────────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING("\n3. История диалога"))
        hist_a = [m["content"] for m in get_history(conv_a)] if conv_a else []
        hist_b = [m["content"] for m in get_history(conv_b)] if conv_b else []
        tally(self._check(any("клинику А" in c for c in hist_a), "История А содержит реплику в А"))
        tally(self._check(
            all("клинику Б" not in c for c in hist_a),
            "История А не содержит ни одной реплики Б",
        ))
        tally(self._check(
            all("клинику А" not in c for c in hist_b),
            "История Б не содержит ни одной реплики А",
        ))
        ctx_a = "\n".join(m["content"] for m in build_messages(clinic_a, conv_a, "ещё вопрос")) if conv_a else ""
        tally(self._check(
            "клинику Б" not in ctx_a and "Имплант-Б-уникальный" not in ctx_a,
            "Контекст модели для А не тянет сообщения/услуги Б",
        ))

        # ── Пункт 4: заявки + уведомление менеджера ─────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING("\n4. Заявки и уведомление менеджера"))
        booking_a = BookingRequest.objects.create(
            clinic=clinic_a,
            conversation=conv_a,
            customer_phone=CUSTOMER_PHONE,
            service="Чистка-А-уникальная",
            preferred_date_raw="завтра",
            preferred_time_raw="в 14",
            status=BookingRequest.Status.NEW,
        )
        tally(self._check(
            BookingRequest.objects.filter(clinic=clinic_b).count() == 0,
            "Заявка А не видна в выборке клиники Б",
        ))
        tally(self._check(
            list(BookingRequest.objects.filter(clinic=clinic_a)) == [booking_a],
            "Выборка клиники А содержит ровно её заявку",
        ))

        notify_provider = self._provider()

        def _dispatch(clinic):
            return notify_provider  # один провайдер — ловим все адреса

        with patch("bookings.tasks.get_whatsapp_provider_for_clinic", side_effect=_dispatch):
            notify_manager.apply(args=[booking_a.id])

        to_a_mgr = [m for m in notify_provider.sent if m["to"] == A_MANAGER]
        to_b_mgr = [m for m in notify_provider.sent if m["to"] == B_MANAGER]
        tally(self._check(len(to_a_mgr) == 1, "Уведомление о заявке А ушло менеджеру А (1 шт.)"))
        tally(self._check(len(to_b_mgr) == 0, "Менеджер Б не получил уведомления о заявке А"))
        booking_a.refresh_from_db()
        tally(self._check(
            booking_a.status == BookingRequest.Status.NOTIFIED,
            "Статус заявки А → notified",
        ))

        # ── Пункт 5: прямой запрос сообщений с фильтром по клинике ───────
        self.stdout.write(self.style.MIGRATE_HEADING("\n5. Прямой запрос сообщений по clinic_id"))
        msgs_a = Message.objects.filter(clinic=clinic_a)
        ids_a = set(msgs_a.values_list("id", flat=True))
        ids_b = set(Message.objects.filter(clinic=clinic_b).values_list("id", flat=True))
        tally(self._check(bool(ids_a) and bool(ids_b), "Сообщения есть и у А, и у Б"))
        tally(self._check(
            all(m.clinic_id == clinic_a.id and m.conversation.clinic_id == clinic_a.id for m in msgs_a),
            "Все строки выборки А принадлежат клинике А (FK + диалог)",
        ))
        tally(self._check(
            ids_a.isdisjoint(ids_b),
            "Выборки сообщений А и Б не пересекаются ни на одной строке",
        ))

        # ── Итог ────────────────────────────────────────────────────────
        self.stdout.write("")
        total = passed + failed
        if failed == 0:
            self.stdout.write(self.style.SUCCESS(
                f"✓ ИЗОЛЯЦИЯ ДОКАЗАНА: все {total} проверок PASS (офлайн, mock)."
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f"✗ {failed}/{total} проверок FAIL — изоляция нарушена."
            ))

        if not options["keep"]:
            self._cleanup()
            self.stdout.write("  (тестовые данные удалены; --keep чтобы оставить)")
        get_ai_provider.cache_clear()
        get_whatsapp_provider.cache_clear()

        if failed:
            raise CommandError(f"{failed} проверок изоляции провалено.")

    def _cleanup(self) -> None:
        """Снести данные прошлого прогона (PROTECT → сначала зависимые таблицы)."""
        clinics = Clinic.objects.filter(instance_name__in=[A_INSTANCE, B_INSTANCE])
        BookingRequest.objects.filter(clinic__in=clinics).delete()
        Message.objects.filter(clinic__in=clinics).delete()
        Conversation.objects.filter(clinic__in=clinics).delete()
        clinics.delete()
