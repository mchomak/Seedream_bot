# i18n_helpers.py
"""Internationalization helpers for the Telegram bot."""

from typing import Optional
from aiogram.types import Message, CallbackQuery, BotCommand
from aiogram import Bot
from sqlalchemy import select
from loguru import logger

from db import Database, User
from text import phrases


async def get_lang(event: Message | CallbackQuery, db: Optional[Database] = None) -> str:
    """
    Resolve user language with priority:
    1) users.lang from DB (if present)
    2) Telegram UI language_code (ru -> ru, otherwise en)
    """
    # Try DB first
    try:
        if db and (getattr(event, "from_user", None) is not None):
            uid = event.from_user.id
            async with db.session() as s:
                row = await s.execute(select(User.lang).where(User.user_id == uid))
                lang = row.scalar_one_or_none()
                if lang and lang in phrases:
                    return lang
    except Exception:
        # don't break flow on DB read error; fallback to UI code
        pass

    # Fallback to Telegram UI language
    code = (getattr(event, "from_user", None) and event.from_user.language_code) or "en"
    return "ru" if code and str(code).lower().startswith("ru") else "en"


def T(locale: str, key: str, **fmt) -> str:
    """Get string from `phrases` with fallback to English."""
    val = phrases.get(locale, {}).get(key) or phrases["en"].get(key) or key
    return val.format(**fmt)


def T_item(locale: str, key: str, subkey: str) -> str:
    """Get nested item e.g. phrases[locale]['help_items']['start']."""
    return (
        phrases.get(locale, {}).get(key, {}).get(subkey)
        or phrases["en"].get(key, {}).get(subkey, subkey)
    )


async def install_bot_commands(bot: Bot, lang: str = "en") -> None:
    """Install bot commands for the given language."""
    items = phrases[lang]["help_items"]
    cmds = [
        BotCommand(command="start", description=items["start"]),
        BotCommand(command="help", description=items["help"]),
        BotCommand(command="profile", description=items["profile"]),
        BotCommand(command="generate", description=items["generate"]),
        BotCommand(command="examples", description=items["examples"]),
        BotCommand(command="buy", description=items["buy"]),
        BotCommand(command="language", description=items["language"]),
        BotCommand(command="cancel", description=items["cancel"]),
    ]
    await bot.set_my_commands(cmds)
    logger.info("Bot commands installed", extra={"lang": lang})
