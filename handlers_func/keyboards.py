# keyboards.py
"""Keyboard builders for the Telegram bot."""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from text import phrases


def _lang_display_name(code: str) -> str:
    """Return autonym for language code."""
    mapping = {
        "ru": "Русский",
        "en": "English",
    }
    return mapping.get(code, code.upper())


def T(locale: str, key: str, **fmt) -> str:
    """Get string from `phrases` with fallback to English."""
    val = phrases.get(locale, {}).get(key) or phrases["en"].get(key) or key
    return val.format(**fmt)


def build_lang_kb() -> InlineKeyboardMarkup:
    """Build language selection keyboard."""
    codes = list(phrases.keys())
    buttons = [
        InlineKeyboardButton(text=_lang_display_name(code), callback_data=f"set_lang:{code}")
        for code in codes
    ]
    # chunk by 2 per row
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_background_keyboard(lang: str, selected: set[str]) -> InlineKeyboardMarkup:
    """
    Клавиатура выбора фона с чекбоксами (галочки на выбранных цветах).
    """
    def btn_text(key: str, phrase_key: str) -> str:
        base = T(lang, phrase_key)
        return f"✅ {base}" if key in selected else base

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=btn_text("white", "btn_bg_white"),
                    callback_data="gen:bg:white",
                ),
                InlineKeyboardButton(
                    text=btn_text("beige", "btn_bg_beige"),
                    callback_data="gen:bg:beige",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=btn_text("pink", "btn_bg_pink"),
                    callback_data="gen:bg:pink",
                ),
                InlineKeyboardButton(
                    text=btn_text("black", "btn_bg_black"),
                    callback_data="gen:bg:black",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=T(lang, "btn_next"),
                    callback_data="gen:bg:next",
                )
            ],
            [
                InlineKeyboardButton(
                    text=T(lang, "btn_back"),
                    callback_data="gen:back_to_types",
                )
            ],
        ]
    )


def build_hair_keyboard(lang: str, selected: set[str]) -> InlineKeyboardMarkup:
    """
    Клавиатура мультивыбора цвета волос с галочками.
    """
    def btn_text(key: str, phrase_key: str) -> str:
        base = T(lang, phrase_key)
        return f"✅ {base}" if key in selected else base

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=btn_text("any", "btn_hair_any"),
                    callback_data="gen:hair:any",
                )
            ],
            [
                InlineKeyboardButton(
                    text=btn_text("dark", "btn_hair_dark"),
                    callback_data="gen:hair:dark",
                )
            ],
            [
                InlineKeyboardButton(
                    text=btn_text("light", "btn_hair_light"),
                    callback_data="gen:hair:light",
                )
            ],
            [
                InlineKeyboardButton(
                    text=T(lang, "btn_next"),
                    callback_data="gen:hair:next",
                )
            ],
            [
                InlineKeyboardButton(
                    text=T(lang, "btn_back"),
                    callback_data="gen:back_to_gender",
                )
            ],
        ]
    )


def build_style_keyboard(lang: str, selected: set[str]) -> InlineKeyboardMarkup:
    """
    Клавиатура мультивыбора стиля фото.
    """
    def btn_text(key: str, phrase_key: str) -> str:
        base = T(lang, phrase_key)
        return f"✅ {base}" if key in selected else base

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=btn_text("strict", "btn_style_strict"),
                    callback_data="gen:style:strict",
                )
            ],
            [
                InlineKeyboardButton(
                    text=btn_text("luxury", "btn_style_luxury"),
                    callback_data="gen:style:luxury",
                )
            ],
            [
                InlineKeyboardButton(
                    text=btn_text("casual", "btn_style_casual"),
                    callback_data="gen:style:casual",
                )
            ],
            [
                InlineKeyboardButton(
                    text=btn_text("sport", "btn_style_sport"),
                    callback_data="gen:style:sport",
                )
            ],
            [
                InlineKeyboardButton(
                    text=T(lang, "btn_next"),
                    callback_data="gen:style:next",
                )
            ],
            [
                InlineKeyboardButton(
                    text=T(lang, "btn_back"),
                    callback_data="gen:back_to_age",
                )
            ],
        ]
    )


def build_aspect_keyboard(lang: str, selected: set[str]) -> InlineKeyboardMarkup:
    """
    Клавиатура мультивыбора соотношения сторон.
    """
    def btn_text(key: str, phrase_key: str) -> str:
        base = T(lang, phrase_key)
        return f"✅ {base}" if key in selected else base

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=btn_text("3_4", "btn_aspect_3_4"),
                    callback_data="gen:aspect:3_4",
                )
            ],
            [
                InlineKeyboardButton(
                    text=btn_text("9_16", "btn_aspect_9_16"),
                    callback_data="gen:aspect:9_16",
                )
            ],
            [
                InlineKeyboardButton(
                    text=btn_text("1_1", "btn_aspect_1_1"),
                    callback_data="gen:aspect:1_1",
                )
            ],
            [
                InlineKeyboardButton(
                    text=btn_text("16_9", "btn_aspect_16_9"),
                    callback_data="gen:aspect:16_9",
                )
            ],
            [
                InlineKeyboardButton(
                    text=T(lang, "btn_next"),
                    callback_data="gen:aspect:next",
                )
            ],
            [
                InlineKeyboardButton(
                    text=T(lang, "btn_back"),
                    callback_data="gen:back_to_style",
                )
            ],
        ]
    )


def build_main_keyboard(lang: str) -> ReplyKeyboardMarkup:
    """Build the persistent main menu keyboard."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=T(lang, "kb_generation")),
                KeyboardButton(text=T(lang, "kb_my_account")),
            ],
            [
                KeyboardButton(text=T(lang, "kb_examples")),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )