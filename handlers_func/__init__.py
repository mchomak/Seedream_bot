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
)
from .i18n_helpers import get_lang, T, T_item, install_bot_commands
from .db_helpers import Profile, get_profile, ensure_credits_and_create_generation

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
]
