"""
Тесты детерминированной стейт-машины записи (фикс-промпт #2) — кейсы со скринов.
На MockProvider, офлайн: `ai=MockAIProvider()` + фиксированный `now` (детерминизм),
mock нормализует даты по TODAY из системного промпта.

Покрываем ровно сценарии задачи:
- «удаление зуба завтра в 15» одним сообщением → 3 слота за раз;
- вопрос о цене посреди записи → цена отвечена, слоты целы, запись продолжается;
- «вчера» → переспрос; «через год» → переспрос конкретной даты;
- «семь утра» при 09:00, «8:59», воскресенье → не приняты;
- «нет/неверно» на подтверждение → заявка НЕ создана, спрашивает что поправить;
- «да» на валидный набор → ровно одна заявка + уведомление менеджеру;
- «массаж» (нет в прайсе) → заявка не создаётся, перечислены реальные услуги.
"""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from unittest.mock import patch

from bookings.flow import _OFFER_ADMIN, _QUESTIONS, _QUESTIONS_RETRY, handle_booking_turn
from bookings.models import BookingRequest
from clinics.models import Clinic
from messaging.models import Conversation
from messaging.tasks import handle_incoming_message
from providers.ai.mock import MockAIProvider
from providers.whatsapp.mock import MockWhatsAppProvider

TZ = ZoneInfo("Asia/Almaty")
# Среда 2026-06-10, 12:00 → «завтра» = четверг 2026-06-11 (рабочий день).
NOW = datetime(2026, 6, 10, 12, 0, tzinfo=TZ)
TOMORROW_ISO = "2026-06-11"

HOURS_BY_DAY = {
    "mon": ["09:00", "20:00"], "tue": ["09:00", "20:00"], "wed": ["09:00", "20:00"],
    "thu": ["09:00", "20:00"], "fri": ["09:00", "20:00"],
    "sat": ["10:00", "18:00"], "sun": None,
}


@pytest.fixture
def clinic(db):
    return Clinic.objects.create(
        name="Жемчуг Дент",
        whatsapp_number="77001112233",
        instance_name="flow_test",
        services_json=[
            {"name": "Профессиональная чистка", "price": "14 000 ₸"},
            {"name": "Удаление зуба", "price": "от 12 000 ₸"},
            {"name": "Отбеливание ZOOM 4", "price": "65 000 ₸"},
        ],
        hours_by_day=HOURS_BY_DAY,
    )


@pytest.fixture
def conversation(clinic):
    return Conversation.objects.create(clinic=clinic, customer_phone="77009998877")


def _turn(conversation, text):
    return handle_booking_turn(conversation, text, conversation.clinic, ai=MockAIProvider(), now=NOW)


# ─────────────────────────── мульти-слот ────────────────────────────────────

@pytest.mark.django_db
def test_multi_slot_one_message(conversation):
    """«удаление зуба завтра в 15» одним сообщением → 3 слота собраны за раз."""
    reply = _turn(conversation, "удаление зуба завтра в 15")

    assert conversation.booking_service == "Удаление зуба"
    assert conversation.booking_date_iso == TOMORROW_ISO
    assert conversation.booking_time == "15:00"
    # Имя из профиля нет → недостающий слот это имя.
    assert reply == _QUESTIONS["name"]
    assert conversation.booking_state == Conversation.BookingState.COLLECTING


# ─────────────────────── вопрос посреди записи ──────────────────────────────

@pytest.mark.django_db
def test_price_question_midbooking_keeps_slots(clinic, settings):
    """Вопрос о цене посреди сбора → цена отвечена (AI), слоты целы, запись идёт."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    conv = Conversation.objects.create(
        clinic=clinic,
        customer_phone="77009998877",
        booking_state=Conversation.BookingState.COLLECTING,
        booking_service="Удаление зуба",
        booking_date_iso=TOMORROW_ISO,
    )

    with (
        patch("messaging.tasks.get_ai_provider", return_value=MockAIProvider()),
        patch("messaging.tasks.get_whatsapp_provider_for_clinic", return_value=MockWhatsAppProvider()),
    ):
        handle_incoming_message(
            clinic_number=clinic.whatsapp_number,
            customer_phone="77009998877",
            text="сколько стоит чистка?",
            external_id="ext-price-1",
        )

    conv.refresh_from_db()
    # Цена отвечена: ответ бота сохранён в БД.
    assert conv.messages.filter(role="assistant").exists()
    # Слоты целы, запись продолжается (состояние не сброшено).
    assert conv.booking_service == "Удаление зуба"
    assert conv.booking_date_iso == TOMORROW_ISO
    assert conv.booking_state == Conversation.BookingState.COLLECTING
    # Заявка НЕ создана.
    assert BookingRequest.objects.filter(conversation=conv).count() == 0


@pytest.mark.django_db
def test_price_question_midbooking_unit_returns_none(clinic):
    """Юнит: вопрос посреди сбора → None (делегирует AI), слоты не тронуты."""
    conv = Conversation.objects.create(
        clinic=clinic,
        customer_phone="77009998877",
        booking_state=Conversation.BookingState.COLLECTING,
        booking_service="Удаление зуба",
    )
    reply = handle_booking_turn(conv, "сколько стоит чистка?", clinic, ai=MockAIProvider(), now=NOW)
    assert reply is None
    conv.refresh_from_db()
    assert conv.booking_service == "Удаление зуба"
    assert conv.booking_state == Conversation.BookingState.COLLECTING


# ───────────────────────── невалидные даты ──────────────────────────────────

@pytest.mark.django_db
def test_date_yesterday_rejected(conversation):
    """«вчера» → дата не принята, переспрос (услуга при этом сохранена)."""
    reply = _turn(conversation, "запишите на удаление зуба вчера")
    assert conversation.booking_service == "Удаление зуба"
    assert conversation.booking_date_iso == ""  # невалидная дата не сохранена
    assert "прошла" in reply.lower()
    assert conversation.booking_state == Conversation.BookingState.COLLECTING


@pytest.mark.django_db
def test_date_next_year_rejected(conversation):
    """«через год» → просим конкретную дату."""
    reply = _turn(conversation, "запишите на удаление зуба через год")
    assert conversation.booking_date_iso == ""
    assert "конкретную дату" in reply.lower()


@pytest.mark.django_db
def test_sunday_rejected(conversation):
    """Воскресенье — выходной → дата не принята."""
    reply = _turn(conversation, "запишите на удаление зуба в воскресенье")
    assert conversation.booking_date_iso == ""
    assert "не работает" in reply.lower()


# ───────────────────────── невалидное время ─────────────────────────────────

def _collecting_with_date(clinic):
    return Conversation.objects.create(
        clinic=clinic,
        customer_phone="77009998877",
        booking_state=Conversation.BookingState.COLLECTING,
        booking_service="Удаление зуба",
        booking_date_iso=TOMORROW_ISO,
    )


@pytest.mark.django_db
def test_seven_am_rejected(clinic):
    """«семь утра» при открытии 09:00 → вне часов, не принято."""
    conv = _collecting_with_date(clinic)
    reply = handle_booking_turn(conv, "в семь утра", clinic, ai=MockAIProvider(), now=NOW)
    assert conv.booking_time == ""
    assert "не работает" in reply.lower()


@pytest.mark.django_db
def test_eight_fiftynine_rejected(clinic):
    """«8:59» → не на сетке 30 минут, не принято."""
    conv = _collecting_with_date(clinic)
    reply = handle_booking_turn(conv, "давайте в 8:59", clinic, ai=MockAIProvider(), now=NOW)
    assert conv.booking_time == ""
    assert "получас" in reply.lower()


# ─────────────────────── гейт подтверждения ─────────────────────────────────

def _awaiting(clinic, **overrides):
    fields = dict(
        clinic=clinic,
        customer_phone="77009998877",
        booking_state=Conversation.BookingState.AWAITING_CONFIRMATION,
        booking_service="Удаление зуба",
        booking_date_iso=TOMORROW_ISO,
        booking_time="15:00",
        booking_name="Иван",
    )
    fields.update(overrides)
    return Conversation.objects.create(**fields)


@pytest.mark.django_db
def test_confirmation_no_does_not_create(clinic):
    """«нет/неверно» на подтверждение → заявка НЕ создана, спрашиваем что поправить."""
    conv = _awaiting(clinic)
    reply = handle_booking_turn(conv, "нет, неверно", clinic, ai=MockAIProvider(), now=NOW)

    assert BookingRequest.objects.filter(conversation=conv).count() == 0
    assert conv.booking_state == Conversation.BookingState.COLLECTING
    assert "поправить" in reply.lower()


@pytest.mark.django_db
def test_confirmation_yes_creates_one_booking_and_notifies(clinic):
    """«да» на валидный набор → ровно одна заявка + уведомление менеджеру."""
    conv = _awaiting(clinic)

    with patch("bookings.flow.notify_manager") as notify:
        reply = handle_booking_turn(conv, "да, верно", clinic, ai=MockAIProvider(), now=NOW)

    bookings = BookingRequest.objects.filter(conversation=conv)
    assert bookings.count() == 1
    booking = bookings.get()
    notify.delay.assert_called_once_with(booking.id)

    # Перенесённые данные.
    assert booking.service == "Удаление зуба"
    assert booking.preferred_date == date(2026, 6, 11)
    assert booking.preferred_time == time(15, 0)
    booking.refresh_from_db()
    assert booking.customer_name == "Иван"
    assert booking.customer_phone == "77009998877"

    # Состояние сброшено, реплика — «передал», НЕ «вы записаны».
    assert conv.booking_state == Conversation.BookingState.IDLE
    assert conv.booking_service == ""
    assert "передал" in reply.lower()


@pytest.mark.django_db
def test_double_yes_does_not_create_second_booking(clinic):
    """После создания заявки повторное «да» (уже idle) не плодит вторую."""
    conv = _awaiting(clinic)
    with patch("bookings.flow.notify_manager"):
        handle_booking_turn(conv, "да", clinic, ai=MockAIProvider(), now=NOW)
        # Второе «да» — состояние уже idle, не запись.
        second = handle_booking_turn(conv, "да", clinic, ai=MockAIProvider(), now=NOW)

    assert second is None
    assert BookingRequest.objects.filter(conversation=conv).count() == 1


# ─────────────────────── неизвестная услуга ─────────────────────────────────

@pytest.mark.django_db
def test_unknown_service_lists_real_services(conversation):
    """«массаж» (нет в прайсе) → заявка не создаётся, перечислены реальные услуги."""
    reply = _turn(conversation, "запишите на массаж завтра в 15")

    assert conversation.booking_service == ""  # услуга не сохранена
    assert "Удаление зуба" in reply
    assert "Профессиональная чистка" in reply
    assert BookingRequest.objects.filter(conversation=conversation).count() == 0
    assert conversation.booking_state == Conversation.BookingState.COLLECTING


# ─────────────────────── полный сбор + подтверждение ────────────────────────

@pytest.mark.django_db
def test_full_collect_then_confirm(clinic):
    """Сбор по шагам → подтверждение → одна заявка (сквозной путь стейт-машины)."""
    conv = Conversation.objects.create(
        clinic=clinic, customer_phone="77009998877", customer_name="Айгерим",
    )

    # Старт: только намерение → спрашиваем услугу.
    assert handle_booking_turn(conv, "хочу записаться", clinic, ai=MockAIProvider(), now=NOW) == _QUESTIONS["service"]
    # Услуга → спрашиваем день.
    assert handle_booking_turn(conv, "удаление зуба", clinic, ai=MockAIProvider(), now=NOW) == _QUESTIONS["date"]
    # День → спрашиваем время.
    assert handle_booking_turn(conv, "завтра", clinic, ai=MockAIProvider(), now=NOW) == _QUESTIONS["time"]
    # Время → имя из профиля есть → сразу подтверждение.
    reply = handle_booking_turn(conv, "в 15:00", clinic, ai=MockAIProvider(), now=NOW)
    assert conv.booking_state == Conversation.BookingState.AWAITING_CONFIRMATION
    assert "Айгерим" in reply and "верно" in reply.lower()

    # Подтверждение → ровно одна заявка.
    with patch("bookings.flow.notify_manager"):
        handle_booking_turn(conv, "да", clinic, ai=MockAIProvider(), now=NOW)
    assert BookingRequest.objects.filter(conversation=conv).count() == 1
    assert conv.booking_state == Conversation.BookingState.IDLE


# ═══════════ Фикс-промпт #3: анти-повтор + реакция на смысл + память ═════════

# ─────────────── вопрос посреди сбора не повторяет слот ──────────────────────

@pytest.mark.django_db
def test_question_in_collecting_does_not_repeat_slot(clinic):
    """Вопрос посреди сбора → делегируем AI (None), слот-вопрос НЕ повторяем,
    счётчик попыток по слоту НЕ растёт (вопрос — это не неудача слота)."""
    conv = Conversation.objects.create(
        clinic=clinic,
        customer_phone="77009998877",
        booking_state=Conversation.BookingState.COLLECTING,
        booking_service="Удаление зуба",  # ждём дату
        booking_slot="date",
        booking_slot_attempts=1,
    )
    reply = _turn(conv, "а сколько стоит чистка?")

    assert reply is None  # ответит обычный AI-флоу, бот не выдаёт слот-вопрос
    conv.refresh_from_db()
    assert conv.booking_service == "Удаление зуба"  # слоты целы
    assert conv.booking_slot_attempts == 1  # вопрос не считается неудачной попыткой
    assert conv.booking_state == Conversation.BookingState.COLLECTING


# ─────────────── 2 неудачи по слоту → админ, а не 3-й повтор ─────────────────

@pytest.mark.django_db
def test_slot_anti_repeat_offers_admin_on_third_try(clinic):
    """Один слот не заполнен 2 раза подряд → 3-го одинакового вопроса НЕТ,
    бот предлагает администратора (1-й вопрос → переформулировка → админ)."""
    conv = Conversation.objects.create(
        clinic=clinic,
        customer_phone="77009998877",
        booking_state=Conversation.BookingState.COLLECTING,
        booking_service="Удаление зуба",  # первый недостающий слот — дата
    )
    r1 = _turn(conv, "не знаю")
    r2 = _turn(conv, "ну хз")
    r3 = _turn(conv, "эээ")

    assert r1 == _QUESTIONS["date"]          # 1-я попытка — обычный вопрос
    assert r2 == _QUESTIONS_RETRY["date"]    # 2-я — переформулировка с примером
    assert r2 != r1
    assert r3 == _OFFER_ADMIN                 # 3-го дословного повтора нет
    assert r3 not in (r1, r2)
    assert "администратор" in r3.lower()

    conv.refresh_from_db()
    assert conv.booking_slot == "date"
    assert conv.booking_slot_attempts >= 3


@pytest.mark.django_db
def test_filling_slot_resets_attempt_counter(clinic):
    """Удачное заполнение слота сбрасывает счётчик попыток (следующий слот — с нуля)."""
    conv = Conversation.objects.create(
        clinic=clinic,
        customer_phone="77009998877",
        booking_state=Conversation.BookingState.COLLECTING,
        booking_service="Удаление зуба",
        booking_slot="date",
        booking_slot_attempts=2,  # по дате уже переспрашивали
    )
    # Пациент наконец называет валидный день → дата заполнена, спрашиваем время.
    reply = _turn(conv, "завтра")
    assert reply == _QUESTIONS["time"]
    conv.refresh_from_db()
    assert conv.booking_date_iso == TOMORROW_ISO
    assert conv.booking_slot == "time"
    assert conv.booking_slot_attempts == 1  # счётчик сброшен на новом слоте


# ─────────────── память о существующей заявке ───────────────────────────────

def _with_existing_booking(clinic, **overrides):
    """Диалог в idle с УЖЕ созданной заявкой (как после подтверждения)."""
    conv = Conversation.objects.create(clinic=clinic, customer_phone="77009998877")
    fields = dict(
        clinic=clinic,
        conversation=conv,
        customer_phone="77009998877",
        customer_name="Иван",
        service="Удаление зуба",
        preferred_date_raw="11.06.2026",
        preferred_time_raw="15:00",
        preferred_date=date(2026, 6, 11),
        preferred_time=time(15, 0),
    )
    fields.update(overrides)
    BookingRequest.objects.create(**fields)
    return conv


@pytest.mark.django_db
def test_recall_existing_booking_states_fact_no_new_collection(clinic):
    """«на что вы меня записали?» → бот называет запись, нового сбора НЕ начинает."""
    conv = _with_existing_booking(clinic)
    reply = _turn(conv, "напомните, на что вы меня записали?")

    assert reply is not None
    assert "Удаление зуба" in reply
    assert "11.06.2026" in reply
    assert "Иван" in reply
    # Нового сбора нет: состояние idle, второй заявки не появилось.
    conv.refresh_from_db()
    assert conv.booking_state == Conversation.BookingState.IDLE
    assert conv.booking_service == ""
    assert BookingRequest.objects.filter(conversation=conv).count() == 1


@pytest.mark.django_db
def test_add_to_existing_booking_refers_and_hands_off(clinic):
    """«добавьте отбеливание к записи» → ссылается на существующую запись и
    передаёт администратору; НЕ зацикливается на дне и не начинает сбор."""
    conv = _with_existing_booking(clinic)
    reply = _turn(conv, "добавьте отбеливание к записи")

    assert "Удаление зуба" in reply             # ссылается на текущую запись
    assert "Отбеливание ZOOM 4" in reply        # называет добавляемую услугу из прайса
    assert "администратор" in reply.lower()      # передаёт человеку
    assert "день" not in reply.lower()           # не спрашивает «на какой день»
    conv.refresh_from_db()
    assert conv.booking_state == Conversation.BookingState.IDLE
    assert BookingRequest.objects.filter(conversation=conv).count() == 1


@pytest.mark.django_db
def test_create_resets_slots_but_keeps_booking_memory(clinic):
    """После создания заявки слоты сброшены (idle), но память о записи жива:
    «вы помните?» отвечает фактом, нового сбора нет (проверка пункта #4)."""
    conv = _awaiting(clinic)  # awaiting_confirmation, имя «Иван»
    with patch("bookings.flow.notify_manager"):
        handle_booking_turn(conv, "да", clinic, ai=MockAIProvider(), now=NOW)

    # Слоты и анти-повтор сброшены, состояние idle.
    assert conv.booking_state == Conversation.BookingState.IDLE
    assert conv.booking_service == ""
    assert conv.booking_slot == ""
    assert conv.booking_slot_attempts == 0

    # Но заявка помнится: «вы помните на что?» → факт, без нового сбора.
    reply = handle_booking_turn(conv, "вы помните на что?", clinic, ai=MockAIProvider(), now=NOW)
    assert reply is not None
    assert "Удаление зуба" in reply
    conv.refresh_from_db()
    assert conv.booking_state == Conversation.BookingState.IDLE
    assert BookingRequest.objects.filter(conversation=conv).count() == 1


@pytest.mark.django_db
def test_existing_booking_appears_in_system_prompt(clinic):
    """Заявка пациента попадает в системный промпт отдельным блоком (для AI-флоу)."""
    from messaging.services import build_messages

    conv = _with_existing_booking(clinic)
    messages = build_messages(clinic, conv, "вы помните на что?")
    system = messages[0]["content"]

    assert "ТЕКУЩАЯ ЗАПИСЬ ПАЦИЕНТА" in system
    assert "Удаление зуба" in system
    assert "11.06.2026" in system
