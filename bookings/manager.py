"""
Ветка менеджера (Фаза 3): менеджер клиники управляет заявками через WhatsApp.

КРИТИЧНО (см. CLAUDE.md): сообщение от номера менеджера (`Clinic.manager_whatsapp`)
НЕ идёт в пациентский флоу и НЕ заводит новую переписку/заявку. Маршрутизатор
(`messaging/tasks.py`) сначала проверяет, не менеджер ли это, и при совпадении
ведёт сообщение СЮДА.

Команды менеджера (в начале сообщения, остальное — заметка для пациента):
  • "+{id}"  или "подтверждаю {id}" → подтвердить заявку #id;
  • "-{id}"  или "отклоняю {id}"    → отклонить заявку #id;
  • текст после команды сохраняется в `manager_note`
    (напр. "+12 приходите к 16:00" → note="приходите к 16:00").

Менеджер может трогать ТОЛЬКО заявки своей клиники (booking.clinic == его клиника).
Чужая заявка → игнор + лог (не раскрываем существование). Неизвестная команда →
короткая подсказка по формату.
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Optional, Tuple

from .models import BookingRequest
from .tasks import notify_customer

if TYPE_CHECKING:
    from clinics.models import Clinic

logger = logging.getLogger(__name__)

# "+12", "+ 12 приходите к 16:00", "подтверждаю 12 ..." → confirm
_CONFIRM_RE = re.compile(r"^\s*(?:\+|подтверждаю)\s*(\d+)\s*(.*)$", re.IGNORECASE | re.DOTALL)
# "-12", "- 12 ...", "отклоняю 12 ..." → reject
_REJECT_RE = re.compile(r"^\s*(?:-|отклоняю)\s*(\d+)\s*(.*)$", re.IGNORECASE | re.DOTALL)

# Подсказка по формату — на неизвестную команду от менеджера.
_HINT = (
    "Не понял команду. Чтобы подтвердить заявку — отправьте «+номер» (например «+12»), "
    "чтобы отклонить — «-номер» (например «-12»). Можно добавить комментарий после "
    "номера: «+12 приходите к 16:00»."
)


def parse_manager_command(text: str) -> Optional[Tuple[str, int, Optional[str]]]:
    """Разобрать команду менеджера → (decision, booking_id, note) или None.

    decision ∈ {"confirm", "reject"}. note — текст после номера (или None).
    None означает «команда не распознана».
    """
    if not text:
        return None
    raw = text.strip()

    m = _CONFIRM_RE.match(raw)
    if m:
        note = m.group(2).strip() or None
        return "confirm", int(m.group(1)), note

    m = _REJECT_RE.match(raw)
    if m:
        note = m.group(2).strip() or None
        return "reject", int(m.group(1)), note

    return None


def apply_manager_decision(
    booking: BookingRequest,
    decision: str,
    note: Optional[str] = None,
) -> BookingRequest:
    """Применить решение менеджера к заявке и уведомить пациента.

    decision "confirm" → status=confirmed; "reject" → status=rejected.
    Заметка (если передана) сохраняется в manager_note. Уведомление пациента —
    через Celery-задачу notify_customer (ровно один вызов на переход).
    """
    if decision == "confirm":
        booking.status = BookingRequest.Status.CONFIRMED
    elif decision == "reject":
        booking.status = BookingRequest.Status.REJECTED
    else:
        raise ValueError(f"Неизвестное решение менеджера: {decision!r}")

    update_fields = ["status", "updated_at"]
    if note:
        booking.manager_note = note
        update_fields.append("manager_note")

    booking.save(update_fields=update_fields)
    notify_customer.delay(booking.id)
    return booking


def handle_manager_message(clinic: "Clinic", text: str) -> Optional[str]:
    """Обработать сообщение менеджера. Вернуть текст ответа менеджеру или None.

    None → отвечать менеджеру не нужно (например, попытка тронуть чужую заявку —
    тихий игнор + лог). Строка → отправить менеджеру (подтверждение/ошибка/подсказка).
    Пациентский флоу при этом НЕ запускается (это решает вызывающий код).
    """
    parsed = parse_manager_command(text)
    if parsed is None:
        return _HINT

    decision, booking_id, note = parsed

    try:
        booking = BookingRequest.objects.select_related("clinic").get(pk=booking_id)
    except BookingRequest.DoesNotExist:
        return f"Заявка #{booking_id} не найдена."

    # Изоляция клиник: менеджер не трогает чужие заявки.
    if booking.clinic_id != clinic.id:
        logger.warning(
            "[manager] менеджер clinic=%s пытался изменить чужую заявку #%s (clinic=%s) — игнор",
            clinic.id,
            booking_id,
            booking.clinic_id,
        )
        return None

    apply_manager_decision(booking, decision, note)

    if decision == "confirm":
        return f"Готово: заявка #{booking_id} подтверждена, пациент уведомлён."
    return f"Готово: заявка #{booking_id} отклонена, пациенту отправлено мягкое уведомление."
