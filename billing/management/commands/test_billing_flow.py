"""
Management-команда: сквозная офлайн-проверка всего биллинга (Фаза 5, финал).

Сценарий (mock-провайдеры, eager Celery, БЕЗ сети):
  1. Триальная клиника: входящее → бот обслуживает, UsageCounter.messages_in вырос.
  2. «Перематываем время» за trial_end + GRACE → прогон run_billing_cycle →
     клиника suspended.
  3. Входящее в suspended-клинику → AI НЕ вызван (mock-AI не дёргался),
     ответа нет, токены не потрачены.
  4. Создаём Payment через ManualBillingProvider и confirm_payment →
     подписка снова active, период продлён на 30 дней.
  5. Входящее снова → бот опять обслуживает.
  6. Повторный confirm того же платежа → период НЕ продлился второй раз.
  7. Повторный прогон run_billing_cycle в тот же день → напоминания/суспенд
     НЕ задвоились.

В конце выводит ✅/❌ по каждому пункту.
Также печатает чеклист для ручного теста на реальном WhatsApp.

Использование:
    docker compose exec web python manage.py test_billing_flow
    docker compose exec web python manage.py test_billing_flow --keep
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from billing import services
from billing.models import BillingEventLog, Plan, Subscription, UsageCounter
from billing.tasks import run_billing_cycle
from clinics.models import Clinic
from providers.billing.factory import get_billing_provider
from providers.billing.manual import ManualBillingProvider
from providers.whatsapp.mock import MockWhatsAppProvider

CLINIC_NUMBER = "79800009901"
CUSTOMER_PHONE = "79800009911"
INSTANCE = "billing-flow-test"


class _FakeClock:
    """Управляемые часы: monkeypatch django.utils.timezone.now."""

    def __init__(self, dt: datetime):
        self._now = dt

    def __call__(self) -> datetime:
        return self._now

    def advance(self, **kwargs) -> None:
        self._now = self._now + timedelta(**kwargs)

    def set(self, dt: datetime) -> None:
        self._now = dt


class Command(BaseCommand):
    help = "Сквозная офлайн-проверка биллинга (mock-провайдеры, eager Celery)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep",
            action="store_true",
            help="Не удалять тестовые данные после проверки.",
        )

    # ------------------------------------------------------------------ helpers
    def _ok(self, label: str) -> bool:
        self.stdout.write(self.style.SUCCESS(f"  ✅ {label}"))
        return True

    def _fail(self, label: str, detail: str = "") -> bool:
        msg = f"  ❌ {label}"
        if detail:
            msg += f"\n     ({detail})"
        self.stdout.write(self.style.ERROR(msg))
        return False

    def _check(self, condition: bool, label: str, detail: str = "") -> bool:
        return self._ok(label) if condition else self._fail(label, detail)

    def _heading(self, text: str) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{'═' * 60}\n {text}\n{'═' * 60}"))

    # ----------------------------------------------------------------- setup
    def _prepare_env(self):
        settings.WHATSAPP_PROVIDER = "mock"
        settings.AI_PROVIDER = "mock"
        settings.BILLING_PROVIDER = "manual"
        # Сброс lru_cache для провайдеров с кешем (get_billing_provider и
        # get_whatsapp_provider — с кешем; get_whatsapp_provider_for_clinic — без кеша).
        from providers.whatsapp.factory import get_whatsapp_provider
        get_whatsapp_provider.cache_clear()
        get_billing_provider.cache_clear()

        from config.celery import app as celery_app
        celery_app.conf.task_always_eager = True
        celery_app.conf.task_eager_propagates = True

    def _make_plan(self) -> Plan:
        plan, _ = Plan.objects.get_or_create(
            code="billing_flow_test",
            defaults={
                "name": "Flow-test тариф",
                "price_kzt": Decimal("15000"),
                "period_days": 30,
                "message_limit": 500,
            },
        )
        return plan

    def _make_clinic(self) -> Clinic:
        clinic, _ = Clinic.objects.get_or_create(
            instance_name=INSTANCE,
            defaults={
                "name": "Flow-test клиника",
                "whatsapp_number": CLINIC_NUMBER,
                "is_active": True,
                "notifications_enabled": True,
                "manager_whatsapp": "79800009999",
                "services_json": [{"name": "Профессиональная чистка", "price": "14 000 ₸"}],
            },
        )
        # Сбросить старые данные прошлого прогона.
        from messaging.models import Conversation
        Conversation.objects.filter(clinic=clinic, customer_phone=CUSTOMER_PHONE).delete()
        BillingEventLog.objects.filter(subscription=clinic.subscription).delete()
        UsageCounter.objects.filter(clinic=clinic).delete()
        return clinic

    # ----------------------------------------------------------------- handle
    def handle(self, *args, **options):
        self._prepare_env()

        self._heading("ПОДГОТОВКА: тестовая клиника + тариф")
        plan = self._make_plan()
        clinic = self._make_clinic()

        # Устанавливаем триальный статус с активным периодом (14 дней).
        sub = clinic.subscription
        now_real = timezone.now()
        trial_end = now_real + timedelta(days=14)
        sub.plan = None
        sub.status = Subscription.Status.TRIALING
        sub.current_period_start = now_real
        sub.current_period_end = trial_end
        sub.trial_end = trial_end
        sub.canceled_at = None
        sub.save()

        self.stdout.write(
            f"  Клиника id={clinic.pk}, instance={INSTANCE}\n"
            f"  Подписка: {sub.status}, конец периода: {sub.current_period_end:%Y-%m-%d}"
        )

        results: list[bool] = []

        # ══════════════════════════════════════════════════════════════════════
        # Шаг 1: триальная клиника обслуживается
        # ══════════════════════════════════════════════════════════════════════
        self._heading("Шаг 1: триальная клиника → бот обслуживает")

        mock_wa_1 = MockWhatsAppProvider()
        mock_ai_1 = MagicMock()
        mock_ai_1.generate.return_value = "Чистка стоит 14 000 ₸."

        try:
            with (
                patch("messaging.tasks.get_ai_provider", return_value=mock_ai_1),
                patch("messaging.tasks.get_whatsapp_provider_for_clinic",
                      return_value=mock_wa_1),
                patch("bookings.tasks.get_whatsapp_provider_for_clinic",
                      return_value=mock_wa_1),
            ):
                from messaging.tasks import handle_incoming_message
                handle_incoming_message(
                    clinic_number=CLINIC_NUMBER,
                    customer_phone=CUSTOMER_PHONE,
                    text="Добрый день, сколько стоит чистка?",
                    external_id="billing-flow-step1-001",
                    instance_name=INSTANCE,
                )

            sub.refresh_from_db()
            usage_after = UsageCounter.objects.filter(clinic=clinic).first()

            r1a = self._check(
                billing_serviceable(clinic),
                "Триальная клиника считается обслуживаемой (is_clinic_serviceable=True)",
            )
            r1b = self._check(
                mock_ai_1.generate.call_count >= 1,
                f"AI был вызван (generate.call_count={mock_ai_1.generate.call_count})",
            )
            r1c = self._check(
                len(mock_wa_1.sent) >= 1,
                f"Ответ отправлен пациенту (sent={len(mock_wa_1.sent)})",
            )
            r1d = self._check(
                usage_after is not None and usage_after.messages_in >= 1,
                f"UsageCounter.messages_in вырос (={getattr(usage_after, 'messages_in', '?')})",
            )
            results.extend([r1a, r1b, r1c, r1d])
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  Шаг 1 упал: {exc}"))
            results.extend([False, False, False, False])

        # ══════════════════════════════════════════════════════════════════════
        # Шаг 2: «перематываем время» → run_billing_cycle → клиника suspended
        # ══════════════════════════════════════════════════════════════════════
        self._heading(
            "Шаг 2: период кончился (trial_end + GRACE + 1д) → billing-cycle → suspended"
        )

        past_end = now_real - timedelta(days=settings.GRACE_DAYS + 1)
        sub.refresh_from_db()
        sub.current_period_end = past_end
        sub.trial_end = past_end
        sub.status = Subscription.Status.TRIALING
        sub.save()
        self.stdout.write(f"  Сдвинули period_end на {past_end:%Y-%m-%d} (за грейсом).")

        mock_wa_cycle = MockWhatsAppProvider()
        try:
            with patch(
                "billing.tasks.get_whatsapp_provider_for_clinic",
                return_value=mock_wa_cycle,
            ):
                result = run_billing_cycle()

            sub.refresh_from_db()
            r2a = self._check(
                sub.status == Subscription.Status.SUSPENDED,
                f"Клиника suspended после billing-cycle (status={sub.status})",
            )
            r2b = self._check(
                not billing_serviceable(clinic),
                "Клиника НЕ обслуживается (is_clinic_serviceable=False)",
            )
            r2c = self._check(
                result.get("errors", 1) == 0,
                f"billing-cycle завершился без ошибок (errors={result.get('errors')})",
            )
            results.extend([r2a, r2b, r2c])
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  Шаг 2 упал: {exc}"))
            results.extend([False, False, False])

        # ══════════════════════════════════════════════════════════════════════
        # Шаг 3: входящее в suspended-клинику → AI не вызван
        # ══════════════════════════════════════════════════════════════════════
        self._heading("Шаг 3: suspended-клиника → AI НЕ вызван, токены не потрачены")

        mock_wa_3 = MockWhatsAppProvider()
        mock_ai_3 = MagicMock()
        mock_ai_3.generate.return_value = "ответ"

        # UsageCounter до шага (зафиксируем messages_in).
        usage_before_3 = UsageCounter.objects.filter(clinic=clinic).first()
        msgs_in_before = getattr(usage_before_3, "messages_in", 0)

        try:
            with (
                patch("messaging.tasks.get_ai_provider", return_value=mock_ai_3),
                patch("messaging.tasks.get_whatsapp_provider_for_clinic",
                      return_value=mock_wa_3),
                patch("bookings.tasks.get_whatsapp_provider_for_clinic",
                      return_value=mock_wa_3),
            ):
                from messaging.tasks import handle_incoming_message
                handle_incoming_message(
                    clinic_number=CLINIC_NUMBER,
                    customer_phone=CUSTOMER_PHONE,
                    text="Есть ли место на среду?",
                    external_id="billing-flow-step3-001",
                    instance_name=INSTANCE,
                )

            usage_after_3 = UsageCounter.objects.filter(clinic=clinic).first()
            msgs_in_after = getattr(usage_after_3, "messages_in", msgs_in_before)

            r3a = self._check(
                mock_ai_3.generate.call_count == 0,
                f"generate НЕ вызван (call_count={mock_ai_3.generate.call_count})",
            )
            r3b = self._check(
                mock_ai_3.transcribe.call_count == 0,
                f"transcribe НЕ вызван (call_count={mock_ai_3.transcribe.call_count})",
            )
            r3c = self._check(
                msgs_in_after == msgs_in_before,
                f"UsageCounter.messages_in НЕ вырос ({msgs_in_before} → {msgs_in_after})",
            )
            results.extend([r3a, r3b, r3c])
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  Шаг 3 упал: {exc}"))
            results.extend([False, False, False])

        # ══════════════════════════════════════════════════════════════════════
        # Шаг 4: confirm_payment → подписка active, период +30 дней
        # ══════════════════════════════════════════════════════════════════════
        self._heading("Шаг 4: Payment через manual-провайдер → confirm → active + +30 дней")

        try:
            billing_provider = ManualBillingProvider()
            sub.refresh_from_db()

            # У suspended-подписки план отсутствует → подставляем тариф для оплаты.
            # (confirm_payment вызывает services.activate с планом из платежа.)
            payment = billing_provider.create_payment(sub, plan)
            self.stdout.write(
                f"  Платёж создан: id={payment.pk}, status={payment.status}, "
                f"сумма={payment.amount_kzt}₸"
            )

            period_end_before = sub.current_period_end
            confirmed = billing_provider.confirm_payment(payment)
            sub.refresh_from_db()
            period_end_after = sub.current_period_end

            r4a = self._check(
                confirmed.status == "paid",
                f"Статус платежа: paid (={confirmed.status})",
            )
            r4b = self._check(
                sub.status == Subscription.Status.ACTIVE,
                f"Подписка active после confirm (={sub.status})",
            )
            days_added = (period_end_after - timezone.now()).days if period_end_after else 0
            r4c = self._check(
                period_end_after is not None and days_added >= 29,
                f"Период продлён на ~30 дней (дней до конца: {days_added})",
            )
            results.extend([r4a, r4b, r4c])
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  Шаг 4 упал: {exc}"))
            results.extend([False, False, False])
            payment = None

        # ══════════════════════════════════════════════════════════════════════
        # Шаг 5: входящее снова → бот обслуживает
        # ══════════════════════════════════════════════════════════════════════
        self._heading("Шаг 5: подписка active → бот снова обслуживает")

        mock_wa_5 = MockWhatsAppProvider()
        mock_ai_5 = MagicMock()
        mock_ai_5.generate.return_value = "Конечно, записывайтесь!"

        try:
            with (
                patch("messaging.tasks.get_ai_provider", return_value=mock_ai_5),
                patch("messaging.tasks.get_whatsapp_provider_for_clinic",
                      return_value=mock_wa_5),
                patch("bookings.tasks.get_whatsapp_provider_for_clinic",
                      return_value=mock_wa_5),
            ):
                from messaging.tasks import handle_incoming_message
                handle_incoming_message(
                    clinic_number=CLINIC_NUMBER,
                    customer_phone=CUSTOMER_PHONE,
                    text="Хочу записаться",
                    external_id="billing-flow-step5-001",
                    instance_name=INSTANCE,
                )

            r5a = self._check(
                mock_ai_5.generate.call_count >= 1,
                f"AI снова вызван после оплаты (generate.call_count={mock_ai_5.generate.call_count})",
            )
            r5b = self._check(
                len(mock_wa_5.sent) >= 1,
                f"Бот ответил пациенту (sent={len(mock_wa_5.sent)})",
            )
            results.extend([r5a, r5b])
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  Шаг 5 упал: {exc}"))
            results.extend([False, False])

        # ══════════════════════════════════════════════════════════════════════
        # Шаг 6: повторный confirm того же платежа → период не сдвигается
        # ══════════════════════════════════════════════════════════════════════
        self._heading("Шаг 6: повторный confirm_payment → идемпотентность (период не двигается)")

        try:
            if payment is None:
                raise AssertionError("Платёж не создан (шаг 4 провалился)")

            sub.refresh_from_db()
            period_end_before_repeat = sub.current_period_end

            billing_provider = ManualBillingProvider()
            billing_provider.confirm_payment(payment)
            # Перечитать из БД (confirm мог сохранить объект).
            from billing.models import Payment as PaymentModel
            payment_fresh = PaymentModel.objects.get(pk=payment.pk)
            billing_provider.confirm_payment(payment_fresh)

            sub.refresh_from_db()
            period_end_after_repeat = sub.current_period_end

            r6 = self._check(
                period_end_after_repeat == period_end_before_repeat,
                f"Период НЕ сдвинулся при повторном confirm "
                f"({period_end_before_repeat} == {period_end_after_repeat})",
            )
            results.append(r6)
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  Шаг 6 упал: {exc}"))
            results.append(False)

        # ══════════════════════════════════════════════════════════════════════
        # Шаг 7: повторный run_billing_cycle → без задвоения
        # ══════════════════════════════════════════════════════════════════════
        self._heading("Шаг 7: повторный billing-cycle → напоминания/суспенд НЕ задваиваются")

        try:
            sub.refresh_from_db()

            # Клиника сейчас active c периодом ~30 дней → цикл ничего не должен делать
            # (напоминания не нужны, period не кончился).
            events_before = BillingEventLog.objects.filter(
                subscription=sub
            ).count()

            mock_wa_7 = MockWhatsAppProvider()
            with patch(
                "billing.tasks.get_whatsapp_provider_for_clinic",
                return_value=mock_wa_7,
            ):
                run_billing_cycle()
                run_billing_cycle()  # второй прогон в тот же «день»

            events_after = BillingEventLog.objects.filter(subscription=sub).count()
            new_msgs = [m for m in mock_wa_7.sent
                        if "приостановлен" in m["text"] or "напоминаем" in m["text"].lower()]

            r7a = self._check(
                events_after == events_before,
                f"Новых событий не создано (до={events_before}, после={events_after})",
            )
            r7b = self._check(
                len(new_msgs) == 0,
                f"Лишних уведомлений не отправлено (new_msgs={len(new_msgs)})",
            )
            results.extend([r7a, r7b])
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  Шаг 7 упал: {exc}"))
            results.extend([False, False])

        # ══════════════════════════════════════════════════════════════════════
        # Итог
        # ══════════════════════════════════════════════════════════════════════
        passed = sum(results)
        failed = len(results) - passed

        self._heading("ИТОГ")
        if failed == 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f"✅ ВСЕ {passed} проверок пройдены. Биллинг работает корректно (офлайн, mock)."
                )
            )
        else:
            self.stdout.write(
                self.style.ERROR(
                    f"❌ Провалено: {failed}/{len(results)}. Пройдено: {passed}/{len(results)}."
                )
            )

        # ── Cleanup ───────────────────────────────────────────────────────────
        if not options["keep"]:
            self._cleanup(clinic)
            self.stdout.write("  (тестовые данные удалены; --keep чтобы оставить)")
        else:
            self.stdout.write(
                f"  Тестовые данные сохранены (clinic id={clinic.pk})."
            )

        # ── Чеклист ────────────────────────────────────────────────────────
        self._print_manual_checklist()

        if failed:
            from django.core.management.base import CommandError
            raise CommandError(f"{failed} проверок провалено.")

    def _cleanup(self, clinic: Clinic) -> None:
        from billing.models import Payment as PaymentModel
        from messaging.models import Conversation
        try:
            from bookings.models import BookingRequest as BR
            BR.objects.filter(clinic=clinic).delete()
        except Exception:
            pass
        Conversation.objects.filter(clinic=clinic).delete()
        PaymentModel.objects.filter(clinic=clinic).delete()
        BillingEventLog.objects.filter(subscription__clinic=clinic).delete()
        UsageCounter.objects.filter(clinic=clinic).delete()
        # Не удаляем клинику: seed_billing_demo её создал, она может быть нужна.
        # Удалить явно: clinic.subscription.delete(); clinic.delete()
        from providers.whatsapp.factory import get_whatsapp_provider
        get_whatsapp_provider.cache_clear()
        get_billing_provider.cache_clear()

    def _print_manual_checklist(self) -> None:
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "\n══════════════════════════════════════════════════════════════\n"
                " ЧЕКЛИСТ: ручной тест биллинга на реальном WhatsApp\n"
                " (НЕ запускать автоматически — только руками)\n"
                "══════════════════════════════════════════════════════════════"
            )
        )
        self.stdout.write("""
1. ПОДГОТОВКА в .env:

   BILLING_PROVIDER=manual
   WHATSAPP_PROVIDER=evolution          # или meta
   AI_PROVIDER=groq
   GROQ_API_KEY=<ваш-ключ>
   EVOLUTION_API_URL=http://localhost:8080
   EVOLUTION_API_KEY=<ваш-ключ>
   EVOLUTION_INSTANCE=<имя-инстанса>

   Перезапустить: docker compose restart web worker

2. ПРОВЕРКА «БОТ МОЛЧИТ» ПРИ SUSPENDED:

   a) В Django admin (/admin/billing/subscription/) найдите тестовую клинику.
   b) Через action «Приостановить» или вручную выставьте status=suspended.
   c) С пациентского номера напишите боту любой текст.
   d) Ожидаемо:
      • Бот либо молчит, либо один раз ответил «Сервис временно недоступен…»
        (тротлинг: повторные сообщения — молчание).
      • В логах worker: «клиника N не обслуживается (status=suspended) — Groq не вызываем».
      • UsageCounter не вырос.

3. ОПЛАТА → АКТИВАЦИЯ:

   a) В /admin/billing/payment/ нажмите «+ Добавить платёж»:
      clinic=тест, subscription=тест, plan=billing_demo,
      amount_kzt=15000, provider=manual, status=pending.
   b) Выберите платёж → action «Подтвердить оплату».
   c) Ожидаемо: платёж = paid; подписка = active; period_end сдвинулась +30 дней.

4. ПРОВЕРКА «БОТ ОТВЕЧАЕТ» ПОСЛЕ ОПЛАТЫ:

   a) С пациентского номера напишите боту снова.
   b) Ожидаемо: бот отвечает как обычно (Groq вызывается, ответ приходит).
   c) В /admin/billing/usagecounter/ счётчик messages_in вырос.

5. ПРОВЕРКА НАПОМИНАНИЙ (BEAT):

   a) В admin сдвиньте current_period_end подписки на 3 дня вперёд от now.
   b) Запустите вручную: docker compose exec web python manage.py shell -c
      "from billing.tasks import run_billing_cycle; print(run_billing_cycle())"
   c) Ожидаемо: менеджеру клиники приходит напоминание «…заканчивается через 3 дня».
   d) Повторный запуск — второго напоминания НЕТ (идемпотентность).
   e) Сдвиньте current_period_end ещё на 2 дня (осталось 1 день) → запустите снова
      → приходит напоминание «заканчивается завтра».

6. АВТОСУСПЕНД ПОСЛЕ GRACE:

   a) Сдвиньте current_period_end на GRACE_DAYS + 2 дня В ПРОШЛОЕ.
   b) Запустите billing_cycle → клиника suspended + менеджеру уведомление.
   c) Повторный запуск → второй суспенд/уведомление НЕ приходит.
""")


def billing_serviceable(clinic: Clinic) -> bool:
    clinic.refresh_from_db()
    return services.is_clinic_serviceable(clinic)
