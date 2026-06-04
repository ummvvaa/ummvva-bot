"""
Тесты модели BookingRequest (Фаза 3). На mock, без сети.

Проверяем:
- заявка создаётся и читается через ORM;
- ПДн пациента (customer_phone) в БД лежат ЗАШИФРОВАННЫМИ (Fernet-токен),
  а через ORM читаются в открытом виде;
- статус по умолчанию = "new";
- (применимость миграций проверяется самим pytest-django — он накатывает
  все миграции на тестовую БД перед прогоном; см. test_migrations_apply_clean).
"""
import datetime

import pytest
from django.db import connection

from bookings.models import BookingRequest
from clinics.models import Clinic


@pytest.fixture
def clinic(db):
    return Clinic.objects.create(name="Тест-клиника", whatsapp_number="77001234567")


@pytest.mark.django_db
def test_booking_request_create_and_read(clinic):
    booking = BookingRequest.objects.create(
        clinic=clinic,
        customer_phone="77009998877",
        customer_name="Айгерим",
        service="Профессиональная чистка",
        preferred_date_raw="завтра",
        preferred_time_raw="после обеда",
        preferred_date=datetime.date(2026, 6, 5),
        preferred_time=datetime.time(15, 0),
    )

    fetched = BookingRequest.objects.get(pk=booking.pk)
    assert fetched.clinic_id == clinic.id
    assert fetched.customer_phone == "77009998877"
    assert fetched.customer_name == "Айгерим"
    assert fetched.service == "Профессиональная чистка"
    assert fetched.preferred_date_raw == "завтра"
    assert fetched.preferred_time_raw == "после обеда"
    assert fetched.preferred_date == datetime.date(2026, 6, 5)
    assert fetched.preferred_time == datetime.time(15, 0)


@pytest.mark.django_db
def test_default_status_is_new(clinic):
    booking = BookingRequest.objects.create(
        clinic=clinic, customer_phone="77001112233"
    )
    assert booking.status == "new"
    assert booking.status == BookingRequest.Status.NEW


@pytest.mark.django_db
def test_customer_name_nullable(clinic):
    # Пациент может не назваться — имя необязательно.
    booking = BookingRequest.objects.create(
        clinic=clinic, customer_phone="77002223344", customer_name=None
    )
    assert BookingRequest.objects.get(pk=booking.pk).customer_name is None


@pytest.mark.django_db
def test_customer_phone_is_encrypted_in_db(clinic):
    """ПДн в БД — шифротекст; через ORM — открытый текст."""
    raw_phone = "77005556677"
    booking = BookingRequest.objects.create(
        clinic=clinic, customer_phone=raw_phone
    )

    # Читаем сырое значение прямо из БД, в обход расшифровки ORM.
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT customer_phone FROM bookings_bookingrequest WHERE id = %s",
            [booking.pk],
        )
        (stored,) = cursor.fetchone()

    # Fernet-поля хранятся как bytea → psycopg отдаёт bytes/memoryview.
    stored_str = bytes(stored).decode() if isinstance(stored, (bytes, memoryview)) else str(stored)

    # В БД лежит Fernet-токен (gAAAA...), а НЕ открытый номер.
    assert raw_phone not in stored_str
    assert stored_str.startswith("gAAAA")

    # А ORM при чтении возвращает открытый текст.
    assert BookingRequest.objects.get(pk=booking.pk).customer_phone == raw_phone


@pytest.mark.django_db
def test_migrations_apply_clean():
    """Миграции применяются чисто.

    Сам факт того, что тестовая БД поднялась (pytest-django накатывает все
    миграции, включая bookings.0001_initial и clinics.0002_*), уже подтверждает
    их применимость. Дополнительно проверяем, что нет неучтённых изменений
    моделей без миграции.
    """
    from io import StringIO

    from django.core.management import call_command

    out = StringIO()
    # --check завершится ненулевым кодом (SystemExit), если есть незакоммиченные
    # изменения моделей без миграции.
    call_command("makemigrations", "--check", "--dry-run", stdout=out)
