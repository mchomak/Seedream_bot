# i18n_helpers.py
"""Internationalization helpers for the Telegram bot (static CSV/JSON localization)."""

from __future__ import annotations

import os
from typing import Optional

from aiogram import Bot
from aiogram.types import Message, CallbackQuery, BotCommand
from loguru import logger
from sqlalchemy import select

from db import Database, User
from localization import Localizer, LocalizerConfig, normalize_lang


# Путь до локализации (экспорт из Google Sheets)
# Рекомендация: хранить в репо как locales/phrases.csv
I18N_PATH = os.getenv("I18N_PATH", "locales/phrases.csv")
DEFAULT_LANG = os.getenv("DEFAULT_LANG", "ru")

i18n = Localizer(
    LocalizerConfig(
        path=I18N_PATH,
        default_lang=DEFAULT_LANG,
        strict_keys=False,  # True, если хотите падать на отсутствующих ключах
    )
).load()


def _supported_lang(code: str | None) -> str:
    """
    Приводит язык к поддерживаемому:
    - exact: en-US
    - base: en
    - default: ru
    """
    code_n = normalize_lang(code, DEFAULT_LANG)

    langs = set(i18n.available_languages())
    if code_n in langs:
        return code_n

    base = code_n.split("-", 1)[0]
    if base in langs:
        return base

    return normalize_lang(DEFAULT_LANG, "ru")


async def get_lang(event: Message | CallbackQuery, db: Optional[Database] = None) -> str:
    """
    Resolve user language with priority:
    1) users.lang from DB (if present)
    2) Telegram UI language_code
    3) default_lang
    """
    # 1) DB
    try:
        if db and getattr(event, "from_user", None) is not None:
            uid = event.from_user.id
            async with db.session() as s:
                row = await s.execute(select(User.lang).where(User.user_id == uid))
                lang = row.scalar_one_or_none()
                if lang:
                    return _supported_lang(lang)
    except Exception:
        # не ломаем поток при ошибке БД
        pass

    # 2) Telegram UI language
    tg_code = (getattr(event, "from_user", None) and event.from_user.language_code) or DEFAULT_LANG
    return _supported_lang(tg_code)


def T(locale: str, key: str, **fmt) -> str:
    # ВАЖНО: locale передаём позиционно, чтобы fmt мог содержать ключ "lang"
    return i18n.t(key, locale, **fmt)


def T_item(locale: str, key: str, subkey: str, **fmt) -> str:
    return i18n.t(f"{key}.{subkey}", locale, **fmt)


async def install_bot_commands(bot: Bot, lang: str = "en") -> None:
    """
    Install bot commands for the given language.
    Берём описания из группы help_items.* (плоские ключи).
    """
    lang = _supported_lang(lang)
    items = i18n.group("help_items", lang=lang)  # {"start": "...", "help": "...", ...}

    cmds = [
        BotCommand(command="start", description=items.get("start", "start")),
        BotCommand(command="help", description=items.get("help", "help")),
        BotCommand(command="profile", description=items.get("profile", "profile")),
        BotCommand(command="generate", description=items.get("generate", "generate")),
        BotCommand(command="examples", description=items.get("examples", "examples")),
        BotCommand(command="buy", description=items.get("buy", "buy")),
        BotCommand(command="language", description=items.get("language", "language")),
        BotCommand(command="cancel", description=items.get("cancel", "cancel")),
    ]
    await bot.set_my_commands(cmds)
    logger.info("Bot commands installed", extra={"lang": lang})
