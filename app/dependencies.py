"""
Dependencies — inyección de dependencias para FastAPI.
"""
from functools import lru_cache
from config.settings import Settings, get_settings


def get_app_settings() -> Settings:
    return get_settings()
