"""
Сборка контекста диалога для AIProvider.generate().

- `get_history` — последние N сообщений диалога в хронологическом порядке.
- `build_messages` — финальный список [system] + история + новое сообщение.

Системные сообщения (Message.Role.SYSTEM) в историю НЕ попадают: системный
промпт собирается заново на каждый запрос из актуальных данных клиники
(см. prompt.build_system_prompt).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from messaging.models import Message
from providers.ai.base import ChatMessage

from .prompt import build_system_prompt

if TYPE_CHECKING:
    from clinics.models import Clinic
    from messaging.models import Conversation

DEFAULT_HISTORY_LIMIT = 10


def get_history(conversation: "Conversation", limit: int = DEFAULT_HISTORY_LIMIT) -> list[ChatMessage]:
    """Вернуть последние `limit` сообщений диалога в формате [{role, content}].

    Порядок — хронологический (старые → новые), как ожидает чат-модель.
    В контекст берём только реплики клиента и бота (user/assistant); системные
    сообщения исключаем — системный промпт подаётся отдельно и собирается заново.
    """
    # Берём последние N через сортировку по убыванию, затем разворачиваем
    # обратно в хронологический порядок (чтобы не тащить весь диалог из БД).
    recent = (
        conversation.messages
        .filter(role__in=[Message.Role.USER, Message.Role.ASSISTANT])
        .order_by("-created_at")[:limit]
    )
    chronological = reversed(list(recent))
    return [{"role": m.role, "content": m.content} for m in chronological]


def build_messages(
    clinic: "Clinic",
    conversation: "Conversation | None",
    new_user_text: str,
    history_limit: int = DEFAULT_HISTORY_LIMIT,
) -> list[ChatMessage]:
    """Собрать финальный список сообщений для AIProvider.generate().

    Структура: [системный промпт] + история последних N сообщений + новое
    сообщение пользователя. `conversation` может быть None (новый диалог,
    истории ещё нет).
    """
    customer_name = getattr(conversation, "customer_name", None) if conversation is not None else None
    messages: list[ChatMessage] = [
        {"role": "system", "content": build_system_prompt(clinic, customer_name=customer_name)}
    ]

    if conversation is not None:
        messages.extend(get_history(conversation, limit=history_limit))

    messages.append({"role": "user", "content": new_user_text})
    return messages
