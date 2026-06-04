"""
Management-команда: создаёт ДВЕ демо-клиники для проверки мультитенанта.

У клиник РАЗНЫЕ инстансы, номера и менеджеры, а главное — РАЗНЫЕ цены на одну и
ту же услугу («Профессиональная чистка», «Отбеливание зубов»). На смоук-тесте это
сразу показывает, что бот не путает прайсы разных клиник.

Идемпотентна: повторный запуск НЕ плодит дубли — клиники находятся/создаются по
`instance_name` (он уникален). Поля обновляются под актуальные демо-данные.

Запуск:
    docker compose exec web python manage.py seed_multitenant_demo
"""
from django.core.management.base import BaseCommand

from clinics.models import Clinic

# ── Клиника А ──────────────────────────────────────────────────────────────────
A = {
    "instance_name": "demo_clinic_a",
    "name": "Жемчуг Дент",
    "whatsapp_number": "77010000001",
    "manager_whatsapp": "77010000009",
    "timezone": "Asia/Almaty",
    "address": "г. Алматы, ул. Назарбаева, 45, офис 102 (ТЦ Меломан, 2 этаж)",
    "services_json": [
        {"name": "Осмотр и консультация врача", "price": "3 000 ₸"},
        # ВНИМАНИЕ: цена на чистку специально отличается от клиники Б.
        {"name": "Профессиональная чистка (ультразвук + Air Flow)", "price": "14 000 ₸"},
        {"name": "Лечение кариеса (1 поверхность)", "price": "от 18 000 ₸"},
        {"name": "Отбеливание зубов (ZOOM 4)", "price": "65 000 ₸"},
        {"name": "Металлокерамическая коронка", "price": "от 65 000 ₸"},
    ],
    "working_hours": {"Пн–Пт": "09:00–20:00", "Сб": "10:00–18:00", "Вс": "выходной"},
    "faq": [
        {"q": "Есть ли рассрочка?", "a": "Да, Kaspi Gold до 12 месяцев без процентов."},
        {"q": "Где находитесь?", "a": "Алматы, ул. Назарбаева, 45, офис 102. Есть парковка."},
    ],
    "tone": (
        "Дружелюбный, на «вы», без жаргона. Информируем честно, не давим. "
        "Не ставим диагнозов — приглашаем на осмотр."
    ),
}

# ── Клиника Б ──────────────────────────────────────────────────────────────────
B = {
    "instance_name": "demo_clinic_b",
    "name": "Дента Люкс",
    "whatsapp_number": "77020000001",
    "manager_whatsapp": "77020000009",
    "timezone": "Asia/Aqtobe",
    "address": "г. Астана, пр. Кабанбай батыра, 12, ВП-3",
    "services_json": [
        {"name": "Осмотр и консультация врача", "price": "5 000 ₸"},
        # ТЕ ЖЕ услуги, что у А, но ДРУГИЕ цены — ключ смоук-теста изоляции.
        {"name": "Профессиональная чистка (ультразвук + Air Flow)", "price": "22 000 ₸"},
        {"name": "Лечение кариеса (1 поверхность)", "price": "от 25 000 ₸"},
        {"name": "Отбеливание зубов (ZOOM 4)", "price": "89 000 ₸"},
        {"name": "Цельнокерамическая вкладка", "price": "от 70 000 ₸"},
    ],
    "working_hours": {"Пн–Сб": "10:00–21:00", "Вс": "11:00–17:00"},
    "faq": [
        {"q": "Работаете в выходные?", "a": "Да, без выходных. Вс — с 11:00 до 17:00."},
        {"q": "Где находитесь?", "a": "Астана, пр. Кабанбай батыра, 12, ВП-3."},
    ],
    "tone": (
        "Тёплый и заботливый, на «вы». Подчёркиваем премиальный сервис, "
        "но без навязывания. Не ставим диагнозов."
    ),
}


class Command(BaseCommand):
    help = "Создаёт две демо-клиники (А и Б) с разными ценами для проверки мультитенанта"

    def handle(self, *args, **options):
        results = [self._upsert(A), self._upsert(B)]

        self.stdout.write(self.style.SUCCESS("\n✓ Демо-клиники для мультитенанта готовы\n"))
        for clinic, created in results:
            tag = "создана" if created else "обновлена (уже была)"
            self.stdout.write(f"  • {clinic.name}  [{tag}]")
            self.stdout.write(f"      id:        {clinic.pk}")
            self.stdout.write(f"      instance:  {clinic.instance_name}")
            self.stdout.write(f"      WhatsApp:  +{clinic.whatsapp_number}")
            self.stdout.write(f"      менеджер:  +{clinic.manager_whatsapp}")
            self.stdout.write(f"      timezone:  {clinic.timezone}")
            self.stdout.write("")

        # Подсказка для смоук-теста: одна и та же услуга — разные цены.
        self.stdout.write(
            "  Проверка изоляции прайсов (одна услуга — разные цены):\n"
            f"    «Профессиональная чистка»:  {self._price(A)}  (А)  vs  {self._price(B)}  (Б)\n"
        )

    def _upsert(self, data: dict) -> tuple[Clinic, bool]:
        """Идемпотентно: ищем/создаём по instance_name, обновляем остальные поля."""
        defaults = {k: v for k, v in data.items() if k != "instance_name"}
        defaults["is_active"] = True
        clinic, created = Clinic.objects.get_or_create(
            instance_name=data["instance_name"], defaults=defaults
        )
        if not created:
            for field, value in defaults.items():
                setattr(clinic, field, value)
            clinic.save()
        return clinic, created

    @staticmethod
    def _price(data: dict) -> str:
        for svc in data["services_json"]:
            if "чистка" in svc["name"].lower():
                return svc["price"]
        return "—"
