"""
Root conftest: переводит тесты на SQLite, чтобы pytest работал без Docker/Postgres.

load_dotenv() по умолчанию НЕ перебивает уже установленные env-переменные, поэтому
достаточно выставить USE_SQLITE_FOR_TESTS=1 здесь — до загрузки settings.py.
"""
import os

# Выставляем ДО любого import Django/settings (conftest читается раньше).
os.environ["USE_SQLITE_FOR_TESTS"] = "1"
