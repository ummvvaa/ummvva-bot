"""
Management-команда: проверяет готовность клиники к работе.

Запуск:
    docker compose exec web python manage.py check_clinic <instance_name>

Показывает:
  • активна ли клиника
  • заполнены ли услуги, часы, адрес, FAQ
  • задан ли менеджер и включены ли уведомления
  • привязан ли инстанс и номер WhatsApp
  • итоговый вердикт: ГОТОВА / ЕСТЬ ПРОБЛЕМЫ

Ошибки (issues) — бот не заработает без их устранения.
Предупреждения (warnings) — бот заработает, но будет неполным.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from clinics.models import Clinic


class Command(BaseCommand):
    help = "Проверить готовность клиники к работе по instance_name"

    def add_arguments(self, parser):
        parser.add_argument(
            "instance_name",
            type=str,
            help="Имя инстанса Evolution (Clinic.instance_name)",
        )

    def handle(self, *args, **options):
        instance_name = options["instance_name"]

        try:
            clinic = Clinic.objects.get(instance_name=instance_name)
        except Clinic.DoesNotExist:
            raise CommandError(
                f"Клиника с instance_name={instance_name!r} не найдена в БД.\n"
                "Создайте запись Clinic в админке и задайте instance_name."
            )

        self.stdout.write(f"\n{'─' * 54}")
        self.stdout.write(f"  Клиника: {clinic.name}  (id={clinic.pk})")
        self.stdout.write(f"{'─' * 54}\n")

        issues: list[str] = []
        warnings: list[str] = []

        # ── Активность ────────────────────────────────────────────────────────
        if clinic.is_active:
            self._ok("Активна (is_active=True)")
        else:
            issues.append("Клиника НЕАКТИВНА (is_active=False) — бот игнорирует входящие")

        # ── Маршрутизация ─────────────────────────────────────────────────────
        if clinic.instance_name:
            self._ok(f"Инстанс задан: {clinic.instance_name}")
        else:
            issues.append(
                "instance_name не задан — маршрутизация по инстансу невозможна"
            )

        if clinic.whatsapp_number:
            self._ok(f"Номер WhatsApp: +{clinic.whatsapp_number}")
        else:
            issues.append(
                "whatsapp_number не задан — резервная маршрутизация по номеру невозможна"
            )

        # ── Контент для бота ──────────────────────────────────────────────────
        svc_count = len(clinic.services_json) if isinstance(clinic.services_json, list) else 0
        if svc_count > 0:
            self._ok(f"Услуги заполнены: {svc_count} позиций")
        else:
            issues.append(
                "services_json пуст — бот не знает прайс и не сможет отвечать на вопросы о ценах"
            )

        if clinic.working_hours:
            days = ", ".join(clinic.working_hours.keys()) if isinstance(clinic.working_hours, dict) else "заданы"
            self._ok(f"Часы работы: {days}")
        else:
            warnings.append("working_hours пусты — бот не знает расписание клиники")

        if clinic.address:
            self._ok(f"Адрес: {clinic.address[:60]}{'…' if len(clinic.address) > 60 else ''}")
        else:
            warnings.append("address пуст — бот не знает адрес клиники")

        faq_count = len(clinic.faq) if isinstance(clinic.faq, list) else 0
        if faq_count > 0:
            self._ok(f"FAQ: {faq_count} вопросов")
        else:
            warnings.append("faq пуст — рекомендуется добавить частые вопросы и ответы")

        # ── Уведомления менеджера ─────────────────────────────────────────────
        if clinic.manager_whatsapp:
            self._ok(f"Менеджер: +{clinic.manager_whatsapp}")
        else:
            warnings.append(
                "manager_whatsapp не задан — уведомления о заявках на запись не отправятся"
            )

        if clinic.manager_whatsapp and not clinic.notifications_enabled:
            warnings.append(
                "notifications_enabled=False — уведомления о заявках выключены"
            )

        # ── Часовой пояс ──────────────────────────────────────────────────────
        self._ok(f"Часовой пояс: {clinic.timezone}")

        # ── Итог ──────────────────────────────────────────────────────────────
        self.stdout.write("")
        if warnings:
            self.stdout.write(self.style.WARNING(f"  Предупреждения ({len(warnings)}):"))
            for w in warnings:
                self.stdout.write(self.style.WARNING(f"    ⚠  {w}"))
            self.stdout.write("")

        if issues:
            self.stdout.write(self.style.ERROR(f"  Ошибки ({len(issues)}):"))
            for e in issues:
                self.stdout.write(self.style.ERROR(f"    ✗  {e}"))
            self.stdout.write("")
            self.stdout.write(self.style.ERROR("  ВЕРДИКТ: КЛИНИКА НЕ ГОТОВА — устрани ошибки выше\n"))
        else:
            self.stdout.write(self.style.SUCCESS("  ВЕРДИКТ: КЛИНИКА ГОТОВА — можно отправлять тестовое сообщение\n"))

    def _ok(self, msg: str) -> None:
        self.stdout.write(self.style.SUCCESS(f"  ✓  {msg}"))
