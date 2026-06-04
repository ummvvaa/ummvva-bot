"""
Celery-задачи обработки входящих сообщений.

Главная склейка Фазы 1 (мультитенант): входящее текстовое сообщение → ответ бота.

Поток (CLAUDE.md, раздел «Поток обработки сообщения»):
  webhook принял входящее → поставил эту задачу → worker:
    1. по номеру-получателю находит клинику (Clinic.whatsapp_number);
    2. get_or_create Conversation(clinic, customer_phone);
    3. дедуп по external_id (WhatsApp шлёт ретраи одного сообщения);
    4. собирает контекст build_messages(clinic, conversation, text);
    5. сохраняет входящее Message(role=user, external_id);
    6. AIProvider.generate() → ответ (с ретраями и fallback при недоступности);
    7. сохраняет Message(role=assistant);
    8. WhatsAppProvider.send_message(customer_phone, ответ).

НЕЗЫБЛЕМОЕ ПРАВИЛО: ни Groq, ни Evolution напрямую — только через фабрики
get_ai_provider() / get_whatsapp_provider_for_clinic().
"""
from __future__ import annotations

import logging

from celery import shared_task

from bookings.flow import finalize_booking, handle_booking_turn
from bookings.manager import handle_manager_message
from bookings.tasks import notify_manager
from clinics.models import Clinic
from messaging.models import Conversation, Message
from messaging.services import build_messages
from providers.ai.factory import get_ai_provider
from providers.whatsapp.factory import get_whatsapp_provider_for_clinic

logger = logging.getLogger(__name__)

# Отправляем клиенту, когда AI недоступен после всех ретраев.
_FALLBACK_REPLY = (
    "Извините, я сейчас не могу ответить — передам ваше сообщение менеджеру. "
    "Ответим в ближайшее время!"
)

# Отправляем клиенту, когда голосовое не удалось скачать/распознать.
_VOICE_FAIL_REPLY = "Не смог разобрать голосовое, повтори текстом, пожалуйста"

# messageType (Evolution), которые приходят как голосовые.
_VOICE_MESSAGE_TYPES = ("audioMessage", "pttMessage")


def _resolve_clinic(instance_name: str, clinic_number: str) -> Clinic | None:
    """Найти клинику по тому, КУДА пришло сообщение (мультитенант-маршрутизация).

    Приоритет:
      1. instance_name — имя инстанса Evolution. Уникален на клинику, не зависит
         от формата номеров — самый надёжный признак получателя.
      2. clinic_number — номер-получатель (whatsapp_number). Запасной ключ, если
         инстанс пуст или клиника по нему не заведена.

    is_active здесь НЕ фильтруем намеренно: клинику опознаём по идентичности, а
    активность проверяет вызывающий код (иначе неактивная клиника по инстансу
    «провалилась» бы в поиск по номеру и могла бы совпасть с ДРУГОЙ клиникой).
    Возвращает Clinic или None, если ни по инстансу, ни по номеру не нашли.
    """
    if instance_name:
        clinic = Clinic.objects.filter(instance_name=instance_name).first()
        if clinic is not None:
            return clinic
    if clinic_number:
        return Clinic.objects.filter(whatsapp_number=clinic_number).first()
    return None


def _booking_confirmation_reply(booking, clinic) -> str:
    """Реплика пациенту после создания заявки. НЕ «вы записаны» — только «передал»."""
    parts = [p for p in [booking.service, booking.preferred_date_raw, booking.preferred_time_raw] if p]
    details = ", ".join(parts) if parts else "детали уточнит администратор"
    return (
        f"Спасибо! Передал заявку администратору клиники «{clinic.name}»: {details}. "
        "Он свяжется с вами и подтвердит точное время."
    )


@shared_task(ignore_result=True)
def handle_incoming_message(
    clinic_number: str,
    customer_phone: str,
    text: str = "",
    external_id: str | None = None,
    instance_name: str = "",
    message_type: str = "conversation",
    push_name: str = "",
) -> None:
    """Обработать одно входящее сообщение (текст или голос) и ответить клиенту.

    Голосовое сообщение распознаётся в текст ДО входа в общий пайплайн, после чего
    обрабатывается ровно так же, как обычный текст (логика ответа не дублируется).

    Все аргументы — примитивы (json-сериализуемые), чтобы корректно проходить
    через брокер Celery.
    """
    # Метка для логов до того, как найдём клинику.
    clinic_hint = f"instance={instance_name or '—'} number={clinic_number or '—'}"

    try:
        # 0. Маршрутизация (мультитенант): по тому, КУДА пришло сообщение —
        #    сначала по instance_name инстанса Evolution, затем по номеру-получателю.
        #    Вся дальнейшая работа идёт СТРОГО в контексте этой клиники.
        clinic = _resolve_clinic(instance_name, clinic_number)
        if clinic is None or not clinic.is_active:
            # Не светим текст сообщения в логах (медданные) — только маршрут-ключи.
            logger.warning(
                "Входящее (instance=%r, number=%r): %s — пропуск.",
                instance_name,
                clinic_number,
                "клиника не найдена" if clinic is None else "клиника неактивна",
            )
            return

        clinic_hint = str(clinic.id)

        # 0a. Это сообщение ОТ МЕНЕДЖЕРА этой клиники? Тогда — ветка менеджера,
        #     НЕ пациента. Проверяем СТРОГО в контексте найденной клиники (а не
        #     глобально по всем клиникам): менеджер клиники A, написавший как
        #     пациент в клинику B, не должен попасть в менеджерскую ветку A.
        #     Делаем это ДО любой пациентской обработки (голос/диалог/запись),
        #     чтобы команды менеджера не заводили новую переписку.
        if clinic.manager_whatsapp and clinic.manager_whatsapp == customer_phone:
            reply = handle_manager_message(clinic, text)
            if reply:
                get_whatsapp_provider_for_clinic(clinic).send_message(customer_phone, reply)
            logger.info(
                "[tasks] сообщение от менеджера обработано (clinic=%s).",
                clinic.id,
            )
            return

        # 0b. Голосовое → текст. Эта ветка ТОЛЬКО превращает аудио в текст;
        #    дальше выполняется тот же текстовый пайплайн (шаги 1–8 ниже).
        if message_type in _VOICE_MESSAGE_TYPES:
            wa = get_whatsapp_provider_for_clinic(clinic)
            # key.id входящего — по нему провайдер отдаёт байты аудио.
            media = wa.download_voice_media(external_id) if external_id else None
            if media is None:
                logger.warning(
                    "[tasks] не удалось скачать голосовое (number=%s, external_id=%s).",
                    clinic_number,
                    external_id,
                )
                wa.send_message(customer_phone, _VOICE_FAIL_REPLY)
                return

            audio_bytes, mimetype = media
            transcript = get_ai_provider().transcribe(audio_bytes, mimetype)
            if not transcript:
                logger.warning(
                    "[tasks] транскрипция пустая (number=%s, external_id=%s).",
                    clinic_number,
                    external_id,
                )
                wa.send_message(customer_phone, _VOICE_FAIL_REPLY)
                return

            logger.info(
                "[tasks] голосовое распознано (number=%s, external_id=%s): %r",
                clinic_number,
                external_id,
                transcript,
            )
            # Дальше — общий текстовый поток обработки.
            text = transcript

        # 2. Диалог: один на пару (клиника, номер клиента). Изоляция: диалог
        #    всегда привязан к найденной клинике — один и тот же номер клиента,
        #    написавший в две клиники, ведёт две независимые беседы.
        conversation, _ = Conversation.objects.get_or_create(
            clinic=clinic, customer_phone=customer_phone
        )

        # 2a. Сохраняем имя из профиля WhatsApp (pushName), только если:
        #     • пришло непустое значение (не перезаписываем пустым);
        #     • имя ещё не было сохранено ранее (не затираем вручную сохранённое).
        if push_name and not conversation.customer_name:
            conversation.customer_name = push_name
            conversation.save(update_fields=["customer_name", "updated_at"])

        # 3. Дедупликация: если это сообщение уже сохранено (ретрай вебхука) — выходим.
        if external_id and conversation.messages.filter(
            role=Message.Role.USER, external_id=external_id
        ).exists():
            logger.info(
                "Дубль входящего external_id=%s (clinic=%s) — пропуск.",
                external_id,
                clinic.id,
            )
            return

        # 4. Контекст для модели собираем ДО сохранения нового сообщения:
        #    build_messages сам добавит `text` как последнюю реплику пользователя,
        #    а историю возьмёт из уже сохранённых сообщений диалога.
        messages = build_messages(clinic, conversation, text)

        # 5. Сохраняем входящее сообщение.
        Message.objects.create(
            conversation=conversation,
            clinic=clinic,
            role=Message.Role.USER,
            content=text,
            external_id=external_id,
        )

        # 6. Флоу записи (Фаза 3). Запускается на каждом входящем до AI-генерации.
        #    Контракт handle_booking_turn (см. докстринг bookings/flow.py):
        #    • str  + stage=collecting → уточняющий вопрос: отправляем, AI не зовём.
        #    • str  + stage=ready      → анти-тупик: создаём заявку + отправляем текст.
        #    • None + stage=ready      → черновик полный: создаём заявку + реплика «передал».
        #    • None + stage=none       → не про запись: обычный AI-флоу.
        booking_result = handle_booking_turn(conversation, text, clinic)
        stage = conversation.booking_stage

        if booking_result is not None:
            # Бот задаёт уточняющий вопрос (collecting) или срабатывает анти-тупик (ready).
            reply = booking_result
            if stage == Conversation.BookingStage.READY:
                # Анти-тупик: создаём заявку с частичными данными, уведомляем менеджера.
                booking = finalize_booking(conversation, clinic)
                notify_manager.delay(booking.id)
        elif stage == Conversation.BookingStage.READY:
            # Черновик собран полностью: создаём заявку и отправляем подтверждение.
            booking = finalize_booking(conversation, clinic)
            notify_manager.delay(booking.id)
            reply = _booking_confirmation_reply(booking, clinic)
        else:
            # Обычный вопрос о ценах/услугах — штатный AI-флоу Фазы 1.
            # При 429 / 5xx GroqAIProvider делает ретраи с exponential backoff.
            try:
                ai = get_ai_provider()
                reply = ai.generate(messages, clinic)
            except Exception as exc:
                logger.error(
                    "[tasks] AI недоступен после ретраев (clinic=%s, phone=%s): %s",
                    clinic.id,
                    customer_phone,
                    type(exc).__name__,
                )
                reply = _FALLBACK_REPLY

        # 7. Сохраняем ответ бота.
        Message.objects.create(
            conversation=conversation,
            clinic=clinic,
            role=Message.Role.ASSISTANT,
            content=reply,
        )
        # Поднимаем updated_at диалога (сортировка списков в admin — по свежести).
        conversation.save(update_fields=["updated_at"])

        # 8. Отправляем ответ клиенту через абстракцию WhatsApp-провайдера.
        wa = get_whatsapp_provider_for_clinic(clinic)
        result = wa.send_message(customer_phone, reply)
        if not result.success:
            logger.error(
                "Не удалось отправить ответ клиенту (clinic=%s): %s",
                clinic.id,
                (result.raw or {}).get("error"),
            )
        else:
            logger.info(
                "Ответ отправлен (clinic=%s, message_id=%s).",
                clinic.id,
                result.message_id,
            )

    except Exception as exc:
        # Ловим всё, что не поймали выше, чтобы не роняли всю Celery-очередь.
        # Контент сообщений в лог не пишем (медданные).
        logger.exception(
            "[tasks] Необработанная ошибка (clinic=%s, phone=%s): %s",
            clinic_hint,
            customer_phone,
            type(exc).__name__,
        )
