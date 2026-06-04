"""
Management-команда: наполнить БД демо-заявками для проверки admin.

1. Берёт (или создаёт) демо-клинику «Жемчуг Дент» (+77001112233).
2. Выставляет manager_whatsapp на тестовый номер (чтобы admin показывал поле).
3. Создаёт несколько BookingRequest в разных статусах — есть что посмотреть
   в /admin/bookings/bookingrequest/.

Запуск:
    docker compose exec web python manage.py seed_booking_demo
    docker compose exec web python manage.py seed_booking_demo --force   # пересоздать
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from bookings.models import BookingRequest
from clinics.models import Clinic

_CLINIC_PHONE = "77001112233"
_MANAGER_PHONE = "77089998877"

_DEMO_BOOKINGS = [
    {
        "customer_phone": "77011111111",
        "customer_name": "Айгерим Ахметова",
        "service": "Профессиональная чистка (ультразвук + Air Flow + полировка)",
        "preferred_date_raw": "завтра",
        "preferred_time_raw": "в 15:00",
        "status": BookingRequest.Status.NEW,
    },
    {
        "customer_phone": "77022222222",
        "customer_name": "Данияр Сейткали",
        "service": "Отбеливание зубов (ZOOM 4)",
        "preferred_date_raw": "пятница",
        "preferred_time_raw": "в 11:00",
        "status": BookingRequest.Status.NOTIFIED,
    },
    {
        "customer_phone": "77033333333",
        "customer_name": "Медина Касымова",
        "service": "Лечение кариеса с анестезией",
        "preferred_date_raw": "понедельник",
        "preferred_time_raw": "в 10:00",
        "status": BookingRequest.Status.CONFIRMED,
        "manager_note": "Кабинет 3, доктор Нурланов",
    },
    {
        "customer_phone": "77044444444",
        "customer_name": None,
        "service": "Осмотр и консультация врача",
        "preferred_date_raw": "сегодня",
        "preferred_time_raw": "в 18:00",
        "status": BookingRequest.Status.REJECTED,
        "manager_note": "На сегодня слотов нет. Позвоните завтра после 9:00.",
    },
]


class Command(BaseCommand):
    help = "Создаёт демо-заявки на запись для тестирования admin-интерфейса"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Удалить существующие демо-заявки и создать заново",
        )

    def handle(self, *args, **options):
        force = options["force"]

        clinic = Clinic.objects.filter(whatsapp_number=_CLINIC_PHONE).first()
        if clinic is None:
            self.stdout.write(
                self.style.WARNING(
                    f"Демо-клиника ({_CLINIC_PHONE}) не найдена. "
                    "Сначала запустите: manage.py seed_demo_clinic"
                )
            )
            return

        # Выставляем manager_whatsapp (нужен для ветки менеджера Фазы 3).
        updated = []
        if not clinic.manager_whatsapp or force:
            clinic.manager_whatsapp = _MANAGER_PHONE
            updated.append("manager_whatsapp")
        if not clinic.notifications_enabled or force:
            clinic.notifications_enabled = True
            updated.append("notifications_enabled")
        if updated:
            clinic.save(update_fields=updated + ["updated_at"])
            self.stdout.write(f"  Клиника обновлена: {', '.join(updated)}")

        self.stdout.write(
            f"  Клиника: {clinic.name} (id={clinic.pk})\n"
            f"  manager_whatsapp: {clinic.manager_whatsapp}"
        )

        # Проверяем, есть ли уже демо-заявки (по нешифрованным полям service/status).
        existing_count = BookingRequest.objects.filter(clinic=clinic).count()

        if existing_count > 0 and not force:
            self.stdout.write(
                self.style.WARNING(
                    f"  В клинике уже {existing_count} заявок. "
                    "Используйте --force для пересоздания."
                )
            )
            return

        # Удалить все заявки клиники, если --force (или если до этого дошли).
        if existing_count > 0:
            deleted, _ = BookingRequest.objects.filter(clinic=clinic).delete()
            self.stdout.write(f"  Удалено старых заявок: {deleted}")

        # Создать демо-заявки.
        created = 0
        for data in _DEMO_BOOKINGS:
            BookingRequest.objects.create(
                clinic=clinic,
                conversation=None,
                **data,
            )
            created += 1
            self.stdout.write(
                f"  ✓ заявка: {data['service'][:40]}... "
                f"[{data['status']}]"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"\n✓ Создано {created} демо-заявок.\n"
                "  Откройте: http://localhost:8000/admin/bookings/bookingrequest/"
            )
        )
