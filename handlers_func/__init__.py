# handlers/__init__.py
"""Handlers package for the Telegram bot.

This package contains modularized helper functions and the main router builder.
"""

from .keyboards import (
    build_lang_kb,
    build_background_keyboard,
    build_hair_keyboard,
    build_style_keyboard,
    build_aspect_keyboard,
    build_main_keyboard
)
from .i18n_helpers import get_lang, T, T_item, install_bot_commands
from .db_helpers import (
    Profile,
    get_profile,
    ensure_credits_and_create_generation,
    get_scenario_price,
    get_system_setting,
    get_free_generations_limit,
    get_single_credit_price_rub,
    get_stars_to_rub_rate,
    calculate_stars_for_rubles,
    get_active_tariffs,
    get_tariff_by_id,
    check_can_generate,
)

__all__ = [
    # Keyboards
    "build_lang_kb",
    "build_background_keyboard",
    "build_hair_keyboard",
    "build_style_keyboard",
    "build_aspect_keyboard",
    # I18n
    "get_lang",
    "T",
    "T_item",
    "install_bot_commands",
    # DB Helpers
    "Profile",
    "get_profile",
    "ensure_credits_and_create_generation",
    "get_scenario_price",
    "get_system_setting",
    "get_free_generations_limit",
    "get_single_credit_price_rub",
    "get_stars_to_rub_rate",
    "calculate_stars_for_rubles",
    "get_active_tariffs",
    "get_tariff_by_id",
    "check_can_generate",
]
