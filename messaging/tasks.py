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
get_ai_provider() / get_whatsapp_provider().
"""
from __future__ import annotations

import logging

from celery import shared_task

from clinics.models import Clinic
from messaging.models import Conversation, Message
from messaging.services import build_messages
from providers.ai.factory import get_ai_provider
from providers.whatsapp.factory import get_whatsapp_provider

logger = logging.getLogger(__name__)

# Отправляем клиенту, когда AI недоступен после всех ретраев.
_FALLBACK_REPLY = (
    "Извините, я сейчас не могу ответить — передам ваше сообщение менеджеру. "
    "Ответим в ближайшее время!"
)


@shared_task(ignore_result=True)
def handle_incoming_message(
    clinic_number: str,
    customer_phone: str,
    text: str,
    external_id: str | None = None,
) -> None:
    """Обработать одно входящее текстовое сообщение и ответить клиенту.

    Все аргументы — примитивы (json-сериализуемые), чтобы корректно проходить
    через брокер Celery.
    """
    # Метка для логов до того, как найдём клинику.
    clinic_hint = f"number={clinic_number}"

    try:
        # 1. Маршрутизация по номеру-получателю (мультитенант).
        clinic = Clinic.objects.filter(
            whatsapp_number=clinic_number, is_active=True
        ).first()
        if clinic is None:
            # Не светим текст сообщения в логах (медданные) — только номер-получатель.
            logger.warning(
                "Входящее на номер %s: активная клиника не найдена — пропуск.",
                clinic_number,
            )
            return

        clinic_hint = str(clinic.id)

        # 2. Диалог: один на пару (клиника, номер клиента).
        conversation, _ = Conversation.objects.get_or_create(
            clinic=clinic, customer_phone=customer_phone
        )

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
            role=Message.Role.USER,
            content=text,
            external_id=external_id,
        )

        # 6. Генерация ответа через абстракцию AI-провайдера.
        #    При 429 / 5xx GroqAIProvider делает ретраи с exponential backoff.
        #    Если все попытки исчерпаны — отправляем клиенту вежливый fallback.
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
            role=Message.Role.ASSISTANT,
            content=reply,
        )
        # Поднимаем updated_at диалога (сортировка списков в admin — по свежести).
        conversation.save(update_fields=["updated_at"])

        # 8. Отправляем ответ клиенту через абстракцию WhatsApp-провайдера.
        wa = get_whatsapp_provider()
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
