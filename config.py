# config.py
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any

from dotenv import load_dotenv as _load_dotenv


class AppEnv(Enum):
    DEV = "dev"
    STAGE = "stage"
    PROD = "prod"


GEN_SCENARIO_PRICES: dict[str, int] = {
    # ключи — условные идентификаторы сценариев
    "initial_generation": 1,       # базовая генерация по фото вещи
    "regenerate_same": 1,          # переделать с теми же настройками
    "regenerate_new": 1,           # переделать с новыми настройками
    "change_pose_once": 1,
    "change_pose_five": 3,
    "change_angle_once": 1,
    "change_angle_five": 3,
    "back_view_no_ref": 1,
    "back_view_with_ref": 2,
    "full_body": 1,
    "upper_body": 1,
    "lower_body": 1,
}
HAIR_KEYS = ("any", "dark", "light")
STYLE_KEYS = ("strict", "luxury", "casual", "sport")
ASPECT_KEYS = ("3_4", "9_16", "1_1", "16_9")
BG_KEYS = ("white", "beige", "pink", "black")

# --- локальные маппинги под конструктор промпта ---
BG_LABELS = {
    "white": ("Белый", "White"),
    "beige": ("Бежевый", "Beige"),
    "pink": ("Розовый", "Pink"),
    "black": ("Чёрный", "Black"),
}
BG_SNIPPETS = {
    "white": "White background",
    "beige": "Beige background",
    "pink": "Pink background",
    "black": "Black background",
}

GENDER_LABELS = {
    "female": ("Женский", "Female"),
    "male": ("Мужской", "Male"),
}

HAIR_LABELS = {
    "any": ("Любой", "Any"),
    "dark": ("Тёмные", "Dark"),
    "light": ("Светлые", "Light"),
}
HAIR_SNIPPETS = {
    "dark": "brunette",
    "light": "blonde",
    "any": None,
}

AGE_LABELS = {
    "young": ("Молодой взрослый", "Young adult"),
    "senior": ("Пожилой", "Senior"),
    "child": ("Ребёнок", "Child"),
    "teen": ("Подросток", "Teenager"),
}
AGE_SNIPPETS = {
    "young": None,
    "senior": "senior",
    "child": "child",
    "teen": "teenage",
}

STYLE_LABELS = {
    "strict": ("Строгий", "Strict"),
    "luxury": ("Люксовый", "Luxury"),
    "casual": ("Кэжуал", "Casual"),
    "sport": ("Спортивный", "Sport"),
}
STYLE_SNIPPETS = {
    "strict": "strict style fashion photo",
    "luxury": "luxury fashion brand style photo",
    "casual": "casual fashion brand style photo",
    "sport": "sports fashion brand style photo",
}

ASPECT_LABELS = {
    "3_4": ("3:4", "3:4"),
    "9_16": ("9:16", "9:16"),
    "1_1": ("1:1", "1:1"),
    "16_9": ("16:9", "16:9"),
}
ASPECT_PARAMS = {
    "3_4": ("portrait_4_3", "4K"),
    "9_16": ("portrait_16_9", "4K"),
    "1_1": ("square_hd", "4K"),
    "16_9": ("landscape_16_9", "4K"),
}


@dataclass(frozen=True)
class Settings:
    """Immutable application settings resolved from ENV."""
    app_name: str
    app_env: AppEnv
    debug: bool
    log_level: str
    telegram_bot_token: str
    database_url: str
    redis_url: Optional[str] = None
    seedream_api: Optional[str] = None


def _to_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_env(env_file: str = ".env") -> Settings:
    """
    Load and validate settings from environment (optionally via .env).
    Raises ValueError if required fields are missing or invalid.
    """
    if _load_dotenv:
        _load_dotenv(dotenv_path=env_file, override=False)

    app_name = os.getenv("APP_NAME", "mybot").strip()
    app_env_str = os.getenv("APP_ENV", "dev").strip().lower()
    log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    debug = _to_bool(os.getenv("DEBUG"), default=(app_env_str != "prod"))

    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()

    database_url = os.getenv("DATABASE_URL").strip()
    redis_url = os.getenv("REDIS_URL")
    seedream_api = os.getenv("SEEDREAM_API")

    try:
        app_env = AppEnv(app_env_str)
    except ValueError:
        allowed = [e.value for e in AppEnv]
        raise ValueError(f"APP_ENV must be one of {allowed} (got: {app_env_str!r}).")

    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required but not set.")

    valid_levels = {"TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if log_level not in valid_levels:
        raise ValueError(f"LOG_LEVEL must be one of {sorted(valid_levels)} (got: {log_level}).")

    if database_url.startswith("sqlite"):
        try:
            path_part = database_url.split("///", 1)[1]
            Path(path_part).parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    return Settings(
        app_name=app_name,
        app_env=app_env,
        debug=debug,
        log_level=log_level,
        telegram_bot_token=token,
        database_url=database_url,
        redis_url=redis_url,
        seedream_api=seedream_api,
    )


def get_runtime_env(settings: Optional[Settings] = None) -> Dict[str, Any]:
    """Normalized runtime snapshot to inject into logs/metrics."""
    settings = settings or load_env()
    env = settings.app_env
    return {
        "env": env.value,
        "is_dev": env is AppEnv.DEV,
        "is_stage": env is AppEnv.STAGE,
        "is_prod": env is AppEnv.PROD,
        "debug": settings.debug,
        "log_level": settings.log_level,
        "app_name": settings.app_name,
    }
