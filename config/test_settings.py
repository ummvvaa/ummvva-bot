"""Test settings: наследует от settings, подменяет DB на SQLite для pytest без Docker."""
import os

os.environ["USE_SQLITE_FOR_TESTS"] = "1"

from .settings import *  # noqa: F401, F403, E402
