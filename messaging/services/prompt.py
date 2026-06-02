"""
Сборка системного промпта из данных клиники.

«Мозг» бота. «Обучение» под клинику — это НЕ файнтюнинг: услуги, цены, часы,
адрес, тон и FAQ подаются сюда, в системный промпт. Модель не дообучается.

Ключевая идея качества ответов: бот отвечает ТОЛЬКО по данным клиники и НЕ
выдумывает цены/факты. Чего не знает — честно говорит и предлагает связать
с менеджером (заявка на запись).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clinics.models import Clinic


# Жёсткие правила поведения бота. Не зависят от конкретной клиники.
BEHAVIOR_RULES = """\
ПРАВИЛА (соблюдай строго):
1. Отвечай ТОЛЬКО на основе данных этой клиники, приведённых ниже. НИКОГДА не
   выдумывай цены, услуги, акции, адреса, часы работы или иные факты, которых
   нет в данных.
2. Если точной цены или информации нет в данных — честно скажи, что не
   располагаешь этой информацией, и предложи связать клиента с менеджером
   клиники (оставить заявку на запись/звонок).
3. Не продавай агрессивно. Твоя задача — дать информацию и мягко помочь
   оставить заявку на приём, если клиент заинтересован. Без навязывания.
4. Будь кратким и по делу: 1–4 предложения, без воды и канцелярита.
5. Не давай медицинских диагнозов и назначений лечения. Общие сведения об
   услугах — можно; диагноз ставит только врач на приёме.
6. Отвечай на том языке, на котором пишет клиент.

ВАЖНО ПРО КАЗАХСКИЙ ЯЗЫК:
Клиент может писать на казахском русскими буквами, без специальных символов
(ә, ғ, қ, ң, ө, ұ, ү, һ, і). Например: «калайсын» = «қалайсың» (как дела),
«рахмет» = «рақмет» (спасибо), «кашан» = «қашан» (когда), «канша» = «қанша»
(сколько). Понимай такой текст как нормальный казахский язык и отвечай
по-казахски (можно тоже обычными русскими буквами, как удобно клиенту)."""


def _format_services(services) -> str:
    """Услуги и цены из services_json → читаемый список.

    Ожидаемый формат элемента: {"name": "...", "price": "..."}.
    Толерантны к свободной структуре: берём name/title и price/cost, иначе
    показываем элемент как есть.
    """
    if not services:
        return "  (услуги не заданы)"
    lines = []
    for item in services:
        if isinstance(item, dict):
            name = item.get("name") or item.get("title") or item.get("service") or "?"
            price = item.get("price") or item.get("cost") or item.get("amount")
            if price:
                lines.append(f"  • {name} — {price}")
            else:
                lines.append(f"  • {name} — цена не указана")
        else:
            lines.append(f"  • {item}")
    return "\n".join(lines)


def _format_working_hours(hours) -> str:
    """Часы работы (dict или строка) → читаемый текст."""
    if not hours:
        return "  (часы работы не заданы)"
    if isinstance(hours, dict):
        return "\n".join(f"  • {day}: {time}" for day, time in hours.items())
    return f"  {hours}"


def _format_faq(faq) -> str:
    """FAQ ([{"q","a"}]) → читаемый список вопрос/ответ."""
    if not faq:
        return ""
    lines = []
    for item in faq:
        if isinstance(item, dict):
            q = item.get("q") or item.get("question")
            a = item.get("a") or item.get("answer")
            if q and a:
                lines.append(f"  • Вопрос: {q}\n    Ответ: {a}")
    if not lines:
        return ""
    return "ЧАСТЫЕ ВОПРОСЫ:\n" + "\n".join(lines)


def build_system_prompt(clinic: "Clinic") -> str:
    """Собрать системный промпт из полей клиники.

    Включает: роль/тон, услуги и цены, часы работы, адрес, FAQ и жёсткие
    правила поведения (отвечать только по данным, не выдумывать, не давить,
    предлагать заявку, понимать казахский русскими буквами).
    """
    name = clinic.name
    tone = (clinic.tone or "").strip() or "Дружелюбный, вежливый, на «вы»."

    parts: list[str] = [
        f"Ты — ассистент стоматологической клиники «{name}» в WhatsApp.",
        "Ты отвечаешь клиентам круглосуточно, когда менеджеры не на связи.",
        "",
        f"ТОН ОБЩЕНИЯ: {tone}",
        "",
        f"КЛИНИКА: {name}",
    ]

    address = (clinic.address or "").strip()
    if address:
        parts.append(f"АДРЕС: {address}")

    parts += [
        "",
        "УСЛУГИ И ЦЕНЫ:",
        _format_services(clinic.services_json),
        "",
        "ЧАСЫ РАБОТЫ:",
        _format_working_hours(clinic.working_hours),
    ]

    faq_block = _format_faq(clinic.faq)
    if faq_block:
        parts += ["", faq_block]

    parts += ["", BEHAVIOR_RULES]

    return "\n".join(parts)
