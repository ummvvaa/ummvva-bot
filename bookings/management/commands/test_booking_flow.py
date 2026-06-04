"""
Management-команда: сквозная проверка флоу записи (Фаза 3, офлайн на mock).

Сценарий:
  Шаг 1. Пациент пишет «хочу записаться на чистку завтра в 3».
          Mock-AI извлекает все слоты → бот создаёт заявку (new→notified)
          и отправляет пациенту «Передал заявку администратору…» (НЕ «вы записаны»).
          Менеджер получает уведомление вида «🦷 Новая заявка #N».

  Шаг 2. Менеджер отвечает «+N».
          Заявка переходит в confirmed → пациент получает
          «✅ Ваша заявка … подтверждена» (НЕ «вы записаны»).

  Проверки:
    - создалась ровно 1 заявка;
    - статусы: new → notified → confirmed;
    - ни в одном сообщении пациенту нет фразы «вы записаны»;
    - тексты менеджеру и пациенту корректные.

  В конце выводится чеклист для ручного теста на реальном Evolution API.

Использование:
    docker compose exec web python manage.py test_booking_flow
    docker compose exec web python manage.py test_booking_flow --keep
"""
from __future__ import annotations

from unittest.mock import patch

from django.conf import settings
from django.core.management.base import BaseCommand

from bookings.models import BookingRequest
from clinics.models import Clinic
from messaging.models import Conversation
from providers.ai.factory import get_ai_provider
from providers.ai.mock import MockAIProvider
from providers.whatsapp.factory import get_whatsapp_provider
from providers.whatsapp.mock import MockWhatsAppProvider

CLINIC_PHONE = "77000009001"
MANAGER_PHONE = "77000009002"
CUSTOMER_PHONE = "77000009003"

_FORBIDDEN_PHRASE = "вы записаны"


class Command(BaseCommand):
    help = "Сквозная проверка флоу записи (mock-провайдеры, eager Celery, офлайн)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep",
            action="store_true",
            help="Не удалять тестовые данные после проверки.",
        )

    def _setup(self) -> None:
        settings.WHATSAPP_PROVIDER = "mock"
        settings.AI_PROVIDER = "mock"
        if "testserver" not in settings.ALLOWED_HOSTS:
            settings.ALLOWED_HOSTS.append("testserver")
        get_ai_provider.cache_clear()
        get_whatsapp_provider.cache_clear()

        from config.celery import app as celery_app

        celery_app.conf.task_always_eager = True
        celery_app.conf.task_eager_propagates = True

    def _check(self, condition: bool, label: str) -> bool:
        if condition:
            self.stdout.write(self.style.SUCCESS(f"    ✓ {label}"))
        else:
            self.stdout.write(self.style.ERROR(f"    ✗ ПРОВАЛЕНО: {label}"))
        return condition

    def handle(self, *args, **options):
        self._setup()

        # ─── Подготовка: тестовая клиника ────────────────────────────────────
        clinic, created = Clinic.objects.get_or_create(
            whatsapp_number=CLINIC_PHONE,
            defaults={
                "name": "Тест-клиника (booking flow)",
                "is_active": True,
                "notifications_enabled": True,
                "services_json": [
                    {
                        "name": "Профессиональная чистка (ультразвук + Air Flow + полировка)",
                        "price": "14 000 ₸",
                    }
                ],
            },
        )
        clinic.manager_whatsapp = MANAGER_PHONE
        clinic.notifications_enabled = True
        clinic.save(update_fields=["manager_whatsapp", "notifications_enabled", "updated_at"])

        # Сбросить данные прошлого прогона.
        Conversation.objects.filter(
            clinic=clinic, customer_phone__in=[CUSTOMER_PHONE, MANAGER_PHONE]
        ).delete()
        BookingRequest.objects.filter(clinic=clinic).delete()

        passed = 0
        failed = 0

        # ─── Шаг 1: пациент пишет «хочу записаться на чистку завтра в 3» ────
        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n═══ Шаг 1: пациент отправляет заявку ═══"
        ))
        self.stdout.write(
            f"  Пациент ({CUSTOMER_PHONE}) → клинике ({CLINIC_PHONE}):\n"
            "  «хочу записаться на чистку завтра в 3»"
        )

        mock_wa = MockWhatsAppProvider()
        mock_ai = MockAIProvider()

        try:
            from messaging.tasks import handle_incoming_message

            with (
                patch("messaging.tasks.get_ai_provider", return_value=mock_ai),
                patch("messaging.tasks.get_whatsapp_provider", return_value=mock_wa),
                patch("bookings.tasks.get_whatsapp_provider", return_value=mock_wa),
            ):
                handle_incoming_message(
                    clinic_number=CLINIC_PHONE,
                    customer_phone=CUSTOMER_PHONE,
                    text="хочу записаться на чистку завтра в 3",
                    external_id="test-booking-flow-001",
                )

            # Ровно одна заявка создана.
            bookings = BookingRequest.objects.filter(clinic=clinic)
            ok = self._check(bookings.count() == 1, "Создалась ровно 1 заявка")
            if not ok:
                raise AssertionError("Ожидалась 1 заявка")
            passed += ok

            booking = bookings.first()
            booking.refresh_from_db()

            # Статус = notified (notify_manager отработал).
            ok = self._check(
                booking.status == BookingRequest.Status.NOTIFIED,
                f"Статус заявки: new → notified (сейчас: {booking.status})"
            )
            passed += ok; failed += not ok

            # Менеджер получил уведомление.
            to_manager = [m for m in mock_wa.sent if m["to"] == MANAGER_PHONE]
            ok = self._check(len(to_manager) >= 1, "Менеджер получил уведомление")
            if ok:
                self.stdout.write(f"    Текст менеджеру: {to_manager[0]['text']!r}")
            passed += ok; failed += not ok

            # Уведомление менеджеру содержит ID заявки и услугу.
            ok = self._check(
                to_manager and str(booking.id) in to_manager[0]["text"],
                "Уведомление менеджеру содержит ID заявки"
            )
            passed += ok; failed += not ok

            ok = self._check(
                to_manager and "чист" in to_manager[0]["text"].lower(),
                "Уведомление менеджеру содержит название услуги"
            )
            passed += ok; failed += not ok

            # Пациент получил «Передал заявку», а НЕ «вы записаны».
            to_patient_step1 = [m for m in mock_wa.sent if m["to"] == CUSTOMER_PHONE]
            ok = self._check(len(to_patient_step1) >= 1, "Пациент получил ответ бота")
            if ok:
                self.stdout.write(f"    Текст пациенту: {to_patient_step1[-1]['text']!r}")
            passed += ok; failed += not ok

            patient_text_1 = to_patient_step1[-1]["text"] if to_patient_step1 else ""
            ok = self._check(
                _FORBIDDEN_PHRASE not in patient_text_1.lower(),
                f"Бот НЕ написал «{_FORBIDDEN_PHRASE}» пациенту"
            )
            passed += ok; failed += not ok

            ok = self._check(
                "администратор" in patient_text_1.lower() or "передал" in patient_text_1.lower(),
                "Бот написал «передал» / «администратор» (а не подтвердил запись)"
            )
            passed += ok; failed += not ok

        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  ✗ Шаг 1 провалился: {exc}"))
            failed += 1

        # ─── Шаг 2: менеджер отвечает «+N» ──────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n═══ Шаг 2: менеджер подтверждает заявку ═══"
        ))

        try:
            booking = BookingRequest.objects.filter(clinic=clinic).first()
            if booking is None:
                raise AssertionError("Заявка не найдена — шаг 1 не прошёл")

            self.stdout.write(
                f"  Менеджер ({MANAGER_PHONE}) → клинике ({CLINIC_PHONE}):\n"
                f"  «+{booking.id}»"
            )

            sent_before = len(mock_wa.sent)

            with (
                patch("messaging.tasks.get_whatsapp_provider", return_value=mock_wa),
                patch("bookings.tasks.get_whatsapp_provider", return_value=mock_wa),
            ):
                handle_incoming_message(
                    clinic_number=CLINIC_PHONE,
                    customer_phone=MANAGER_PHONE,
                    text=f"+{booking.id}",
                    external_id="test-booking-flow-mgr-001",
                )

            booking.refresh_from_db()

            # Статус = confirmed.
            ok = self._check(
                booking.status == BookingRequest.Status.CONFIRMED,
                f"Статус заявки: notified → confirmed (сейчас: {booking.status})"
            )
            passed += ok; failed += not ok

            # Пациент получил «✅ подтверждена».
            new_messages = mock_wa.sent[sent_before:]
            to_patient_step2 = [m for m in new_messages if m["to"] == CUSTOMER_PHONE]

            ok = self._check(len(to_patient_step2) == 1, "Пациент получил ровно одно подтверждение")
            if ok:
                self.stdout.write(f"    Текст пациенту: {to_patient_step2[0]['text']!r}")
            passed += ok; failed += not ok

            patient_text_2 = to_patient_step2[0]["text"] if to_patient_step2 else ""

            ok = self._check(
                "подтверждена" in patient_text_2.lower(),
                "Текст пациенту содержит «подтверждена»"
            )
            passed += ok; failed += not ok

            ok = self._check(
                _FORBIDDEN_PHRASE not in patient_text_2.lower(),
                f"Бот НЕ написал «{_FORBIDDEN_PHRASE}» в подтверждении пациенту"
            )
            passed += ok; failed += not ok

            # Менеджер получил «Готово: подтверждена».
            to_manager_step2 = [m for m in new_messages if m["to"] == MANAGER_PHONE]
            ok = self._check(len(to_manager_step2) >= 1, "Менеджер получил ответ на команду")
            if ok:
                self.stdout.write(f"    Ответ менеджеру: {to_manager_step2[0]['text']!r}")
            passed += ok; failed += not ok

            # Ни в одном сообщении пациенту нет «вы записаны».
            all_to_patient = [m["text"] for m in mock_wa.sent if m["to"] == CUSTOMER_PHONE]
            any_forbidden = any(_FORBIDDEN_PHRASE in t.lower() for t in all_to_patient)
            ok = self._check(
                not any_forbidden,
                f"Ни в одном сообщении пациенту нет фразы «{_FORBIDDEN_PHRASE}»"
            )
            passed += ok; failed += not ok

        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  ✗ Шаг 2 провалился: {exc}"))
            failed += 1

        # ─── Итог ────────────────────────────────────────────────────────────
        self.stdout.write("")
        if failed == 0:
            self.stdout.write(self.style.SUCCESS(
                f"✓ Все {passed} проверок прошли успешно. "
                "Флоу записи работает корректно (офлайн, mock)."
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f"✗ {failed} проверок провалено, {passed} прошло."
            ))

        # ─── Cleanup ─────────────────────────────────────────────────────────
        if not options["keep"]:
            Conversation.objects.filter(
                clinic=clinic, customer_phone__in=[CUSTOMER_PHONE, MANAGER_PHONE]
            ).delete()
            BookingRequest.objects.filter(clinic=clinic).delete()
            if created:
                clinic.delete()
            self.stdout.write("  (тестовые данные удалены; --keep чтобы оставить)")
            get_ai_provider.cache_clear()
            get_whatsapp_provider.cache_clear()

        # ─── Чеклист ручного E2E на реальном WhatsApp ────────────────────────
        self._print_manual_checklist()

        if failed:
            from django.core.management.base import CommandError
            raise CommandError(f"{failed} проверок провалено.")

    def _print_manual_checklist(self) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n═══════════════════════════════════════════════════════════════\n"
            " ЧЕКЛИСТ: ручной E2E на реальном WhatsApp (Evolution API)\n"
            "═══════════════════════════════════════════════════════════════"
        ))
        self.stdout.write("""
Требования: Evolution API запущен, инстанс привязан к SIM-карте клиники,
webhook прописан на /webhook/whatsapp/.

1. ПОДГОТОВКА (в .env и manage.py):

   a) Выставить реальные провайдеры:
      AI_PROVIDER=groq
      WHATSAPP_PROVIDER=evolution
      EVOLUTION_API_URL=http://localhost:8080
      EVOLUTION_API_KEY=<ваш-ключ>
      EVOLUTION_INSTANCE=<имя-инстанса>
      GROQ_API_KEY=<ваш-ключ>

   b) Добавить номер менеджера в demo-клинику (через admin или seed_booking_demo):
      MANAGER_PHONE — ваш второй номер телефона, на который придут уведомления о заявках.
      В Django admin откройте клинику «Жемчуг Дент» и заполните «WhatsApp менеджера».

   c) Перезапустить web и worker:
      docker compose restart web worker

2. ТЕСТ ЗАПИСИ (с «пациентского» номера):

   a) Напишите с пациентского номера на номер клиники:
      «запишите на чистку завтра в 15»

      Ожидаемый ответ бота: «Спасибо! Передал заявку администратору клиники…»
      (без «вы записаны» / «запись подтверждена»)

   b) На номер МЕНЕДЖЕРА должно прийти уведомление:
      «🦷 Новая заявка #N — Жемчуг Дент
       Услуга: Профессиональная чистка…
       Желаемо: завтра 15
       Пациент: —, <номер>
       Ответьте: "+N" чтобы подтвердить или "-N" чтобы отклонить.»

   c) Ответьте с номера МЕНЕДЖЕРА «+N» (номер заявки из уведомления).

      Ожидаемый ответ менеджеру: «Готово: заявка #N подтверждена, пациент уведомлён.»

      Ожидаемый ответ ПАЦИЕНТУ: «✅ Ваша заявка в «Жемчуг Дент» подтверждена: …»
      (без «вы записаны»)

   d) В Django admin (/admin/bookings/bookingrequest/) статус заявки = confirmed.

3. ТЕСТ КАЗАХСКОГО (с пациентского номера):

   Напишите: «ертен жазылайын»  (казахский: «завтра хочу записаться»)

   Ожидаемо: Groq распознаёт намерение записаться, бот спрашивает услугу и время.
   Продолжайте диалог: укажите услугу и время.
   После сбора трёх слотов: менеджеру придёт уведомление (та же логика, что в п.2).

4. ПРОВЕРКА ИЗОЛЯЦИИ (если есть вторая клиника):

   Убедитесь, что сообщения пациента клиники A не видны в admin клиники B.
   Менеджер клиники A не может подтвердить заявку клиники B (ответ игнорируется).
""")
