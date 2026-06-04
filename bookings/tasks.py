"""Celery-задачи для заявок на запись (Фаза 3)."""
from __future__ import annotations

import logging

import requests
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError

from bookings.models import BookingRequest
from providers.whatsapp.factory import get_whatsapp_provider_for_clinic

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3


@shared_task(bind=True, ignore_result=True, max_retries=_MAX_RETRIES)
def notify_manager(self, booking_id: int) -> None:
    """Уведомить менеджера клиники о новой заявке через WhatsApp.

    Запускается через .delay(booking.id) сразу после finalize_booking.
    При успехе → status="notified".
    На сетевую ошибку → Celery retry с exponential backoff (макс. 3 попытки).
    Если уведомления выключены или нет номера → выходим тихо (status="new").
    """
    try:
        booking = BookingRequest.objects.select_related("clinic").get(pk=booking_id)
    except BookingRequest.DoesNotExist:
        logger.error("[notify_manager] заявка #%s не найдена", booking_id)
        return

    clinic = booking.clinic

    if not clinic.notifications_enabled:
        logger.info(
            "[notify_manager] уведомления выключены (clinic=%s, booking=%s)",
            clinic.pk,
            booking_id,
        )
        return

    if not clinic.manager_whatsapp:
        logger.info(
            "[notify_manager] нет номера менеджера (clinic=%s, booking=%s)",
            clinic.pk,
            booking_id,
        )
        return

    name_display = booking.customer_name or "—"
    phone_display = booking.customer_phone or "—"
    date_time = " ".join(
        p for p in [booking.preferred_date_raw, booking.preferred_time_raw] if p
    ) or "не указано"

    text = (
        f"🦷 Новая заявка #{booking_id} — {clinic.name}\n"
        f"Услуга: {booking.service or 'не указана'}\n"
        f"Желаемо: {date_time}\n"
        f"Пациент: {name_display}, {phone_display}\n"
        f'Ответьте: "+{booking_id}" чтобы подтвердить или "-{booking_id}" чтобы отклонить.'
    )

    try:
        wa = get_whatsapp_provider_for_clinic(clinic)
        result = wa.send_message(clinic.manager_whatsapp, text)
        if result.success:
            booking.status = BookingRequest.Status.NOTIFIED
            booking.save(update_fields=["status", "updated_at"])
            logger.info(
                "[notify_manager] менеджер уведомлён (clinic=%s, booking=%s)",
                clinic.pk,
                booking_id,
            )
        else:
            logger.error(
                "[notify_manager] send вернул неуспех (clinic=%s, booking=%s): %s",
                clinic.pk,
                booking_id,
                (result.raw or {}).get("error"),
            )
    except requests.RequestException as exc:
        logger.warning(
            "[notify_manager] сетевая ошибка, retry %d/%d (clinic=%s, booking=%s): %s",
            self.request.retries + 1,
            _MAX_RETRIES,
            clinic.pk,
            booking_id,
            type(exc).__name__,
        )
        try:
            raise self.retry(exc=exc, countdown=2**self.request.retries)
        except MaxRetriesExceededError:
            logger.error(
                "[notify_manager] превышен лимит ретраев (clinic=%s, booking=%s)",
                clinic.pk,
                booking_id,
            )
    except Exception as exc:
        logger.error(
            "[notify_manager] ошибка отправки (clinic=%s, booking=%s): %s",
            clinic.pk,
            booking_id,
            type(exc).__name__,
        )


def _customer_reply(booking) -> str | None:
    """Текст уведомления пациенту по решению менеджера.

    confirmed — подтверждение с деталями и заметкой менеджера (если есть).
    rejected  — мягкое «уточним время», без негатива.
    Иные статусы — None (уведомлять нечего).
    """
    clinic = booking.clinic
    note = (booking.manager_note or "").strip()

    if booking.status == BookingRequest.Status.CONFIRMED:
        when = " ".join(
            p for p in [booking.preferred_date_raw, booking.preferred_time_raw] if p
        )
        details = booking.service or "приём"
        if when:
            details = f"{details}, {when}"
        note_part = f" {note}." if note else ""
        return (
            f"✅ Ваша заявка в «{clinic.name}» подтверждена: {details}."
            f"{note_part} Ждём вас!"
        )

    if booking.status == BookingRequest.Status.REJECTED:
        tail = note or "свяжется с вами"
        return (
            f"По заявке в «{clinic.name}» администратор предложил уточнить время: "
            f"{tail}."
        )

    return None


@shared_task(bind=True, ignore_result=True, max_retries=_MAX_RETRIES)
def notify_customer(self, booking_id: int) -> None:
    """Сообщить пациенту решение менеджера (подтверждение/отказ) через WhatsApp.

    Запускается ровно один раз на переход заявки в confirmed/rejected — из
    apply_manager_decision (ответ менеджера в WhatsApp) либо из admin save_model
    (смена статуса руками). При успехе ничего не меняет в статусе.
    На сетевую ошибку → Celery retry с exponential backoff (макс. 3 попытки).
    """
    try:
        booking = BookingRequest.objects.select_related("clinic").get(pk=booking_id)
    except BookingRequest.DoesNotExist:
        logger.error("[notify_customer] заявка #%s не найдена", booking_id)
        return

    text = _customer_reply(booking)
    if text is None:
        logger.info(
            "[notify_customer] статус %s не требует уведомления (booking=%s)",
            booking.status,
            booking_id,
        )
        return

    if not booking.customer_phone:
        logger.warning("[notify_customer] нет номера пациента (booking=%s)", booking_id)
        return

    try:
        wa = get_whatsapp_provider_for_clinic(booking.clinic)
        result = wa.send_message(booking.customer_phone, text)
        if result.success:
            logger.info(
                "[notify_customer] пациент уведомлён (clinic=%s, booking=%s, status=%s)",
                booking.clinic_id,
                booking_id,
                booking.status,
            )
        else:
            logger.error(
                "[notify_customer] send вернул неуспех (clinic=%s, booking=%s): %s",
                booking.clinic_id,
                booking_id,
                (result.raw or {}).get("error"),
            )
    except requests.RequestException as exc:
        logger.warning(
            "[notify_customer] сетевая ошибка, retry %d/%d (clinic=%s, booking=%s): %s",
            self.request.retries + 1,
            _MAX_RETRIES,
            booking.clinic_id,
            booking_id,
            type(exc).__name__,
        )
        try:
            raise self.retry(exc=exc, countdown=2**self.request.retries)
        except MaxRetriesExceededError:
            logger.error(
                "[notify_customer] превышен лимит ретраев (clinic=%s, booking=%s)",
                booking.clinic_id,
                booking_id,
            )
    except Exception as exc:
        logger.error(
            "[notify_customer] ошибка отправки (clinic=%s, booking=%s): %s",
            booking.clinic_id,
            booking_id,
            type(exc).__name__,
        )
