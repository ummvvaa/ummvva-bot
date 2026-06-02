"""
Бизнес-логика «мозга» бота.

- `prompt.build_system_prompt(clinic)` — системный промпт из данных клиники.
- `conversation.get_history(conversation, limit)` — история диалога для контекста.
- `conversation.build_messages(...)` — финальный список для AIProvider.generate().
"""
from .conversation import build_messages, get_history
from .prompt import build_system_prompt

__all__ = ["build_system_prompt", "get_history", "build_messages"]
