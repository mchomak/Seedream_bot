# handlers.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Any

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
    BotCommand,
    LabeledPrice,
    PreCheckoutQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)
from loguru import logger
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db import (
    Database,
    User,
    Transaction,
    TransactionKind,
    TransactionStatus,
    Generation,
    GenerationStatus,
    upsert_user_basic,
    record_transaction,
    create_generation,
)
from fsm import PaymentFlow, set_waiting_payment, PaymentGuard
from text import phrases
from seedream_service import SeedreamService
from config import *
import asyncio
import json
from io import BytesIO


# ---------- i18n helpers ----------
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


# ---------- commands install ----------


async def install_bot_commands(bot: Bot, lang: str = "en") -> None:
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


# ---------- profile ----------


@dataclass
class Profile:
    user: Optional[User]
    txn_count: int
    txn_sum: Decimal
    currency: str
    credits_balance: int
    money_balance: Decimal


async def get_profile(session: AsyncSession, *, tg_user_id: int) -> Profile:
    """Return user profile with succeeded tx stats and credits/money balances."""
    user = (
        await session.execute(select(User).where(User.user_id == tg_user_id))
    ).scalar_one_or_none()

    stats = (
        await session.execute(
            select(
                func.count(Transaction.id),
                func.coalesce(func.sum(Transaction.amount), 0),
                func.coalesce(func.max(Transaction.currency), "XTR"),
            ).where(
                (Transaction.user_id == tg_user_id)
                & (Transaction.status == TransactionStatus.succeeded)
            )
        )
    ).first()

    txn_count = int(stats[0] or 0)
    txn_sum = Decimal(str(stats[1] or 0))
    currency = str(stats[2] or "XTR")

    credits_balance = int(user.credits_balance) if user else 0
    money_balance = (
        Decimal(str(user.money_balance)) if (user and user.money_balance is not None) else Decimal("0.00")
    )

    return Profile(
        user=user,
        txn_count=txn_count,
        txn_sum=txn_sum,
        currency=currency,
        credits_balance=credits_balance,
        money_balance=money_balance,
    )


async def ensure_credits_and_create_generation(
    session: AsyncSession,
    *,
    tg_user_id: int,
    prompt: str,
    scenario_key: str,
    total_images_planned: int,
    params: Optional[dict[str, Any]] = None,
    source_image_urls: Optional[list[str]] = None,
) -> tuple[Optional[Generation], Optional[User], int]:
    """
    Проверить баланс, списать кредиты и создать Generation.

    Возвращает (generation | None, user | None, price_credits).
    Если кредитов не хватило — generation=None, user=None.
    """
    # узнаём цену сценария
    price = GEN_SCENARIO_PRICES.get(scenario_key, 1)

    user = (
        await session.execute(select(User).where(User.user_id == tg_user_id))
    ).scalar_one_or_none()

    if user is None:
        return None, None, price

    current_balance = int(user.credits_balance or 0)
    if current_balance < price:
        return None, user, price

    # списываем кредиты
    user.credits_balance = current_balance - price

    # создаём запись Generation
    generation = await create_generation(
        session,
        user_id=tg_user_id,
        prompt=prompt,
        model_name="seedream-4.0",
        params=params,
        source_image_urls=source_image_urls,
        total_images_planned=total_images_planned,
        credits_spent=price,
        status=GenerationStatus.queued,
        external_id=None,
    )
    # session.add(generation) уже внутри create_generation
    return generation, user, price


# ---------- payments (Stars) ----------
class StarsPay:
    """Telegram Stars payment helper."""

    def __init__(self, db: Database):
        self.db = db

    async def send_invoice(
        self,
        m: Message,
        state: FSMContext,
        *,
        title: str,
        desc: str,
        stars: int,
        payload: str,
    ) -> None:
        """Send XTR invoice and store waiting state in FSM."""
        prices = [LabeledPrice(label=title, amount=stars)]
        sent = await m.answer_invoice(
            title=title,
            description=desc,
            payload=payload,
            provider_token="",  # Stars for digital goods
            currency="XTR",
            prices=prices,
        )
        await set_waiting_payment(
            state,
            chat_id=sent.chat.id,
            message_id=sent.message_id,
            payload=payload,
            amount=str(stars),
            currency="XTR",
        )

    async def pre_checkout_handler(self, query: PreCheckoutQuery) -> None:
        """Confirm pre-checkout (place to check stock/limits if needed)."""
        await query.answer(ok=True)

    async def on_successful_payment(self, mes: Message, state: FSMContext) -> None:
        """
        Handle successful payment:
          - delete invoice message (Bot API cannot edit invoices)
          - upsert user, record transaction, increase credits balance
          - clear FSM state
        """
        sp = mes.successful_payment
        if not sp:
            return

        user_id = mes.from_user.id if mes.from_user else None
        # В Stars total_amount уже в "звёздах" (единицах)
        amount_stars = int(sp.total_amount)
        payload = sp.invoice_payload
        charge_id = getattr(sp, "telegram_payment_charge_id", None)

        # Try to delete the stored invoice message (visual "edit" effect)
        data = await state.get_data()
        inv_chat_id = data.get("invoice_chat_id")
        inv_msg_id = data.get("invoice_message_id")
        if inv_chat_id and inv_msg_id:
            try:
                await mes.bot.delete_message(chat_id=inv_chat_id, message_id=inv_msg_id)
            except Exception:
                pass

        async with self.db.session() as s:
            await upsert_user_basic(
                s,
                user_id=user_id,
                tg_username=mes.from_user.username if mes.from_user else None,
                lang=(mes.from_user.language_code if mes.from_user else None),
                last_seen_at=datetime.now(timezone.utc),
                is_premium=getattr(mes.from_user, "is_premium", False)
                if mes.from_user
                else False,
                is_bot=mes.from_user.is_bot if mes.from_user else False,
            )

            await record_transaction(
                s,
                user_id=user_id,
                kind=TransactionKind.purchase,
                amount=Decimal(amount_stars),
                currency="XTR",
                provider="telegram_stars",
                status=TransactionStatus.succeeded,
                title="Stars purchase",
                external_id=charge_id or payload,
                meta={"payload": payload},
            )

            db_user = (
                await s.execute(select(User).where(User.user_id == user_id))
            ).scalar_one_or_none()
            if db_user:
                # Интерпретируем 1 звезду = 1 кредит генерации
                db_user.credits_balance = (db_user.credits_balance or 0) + amount_stars

        await state.clear()

        lang = await get_lang(mes, self.db)
        await mes.answer(
            T(
                lang,
                "payment_ok",
                charge_id=charge_id or "-",
                amount=str(amount_stars),
            )
        )
        logger.info(
            "Stars payment succeeded",
            extra={
                "user_id": user_id,
                "invoice_payload": payload,
                "charge_id": charge_id,
                "amount_stars": amount_stars,
            },
        )


# ---------- language utils ----------


def _lang_display_name(code: str) -> str:
    # simple autonyms; fallback to uppercased code
    mapping = {
        "ru": "Русский",
        "en": "English",
    }
    return mapping.get(code, code.upper())


def _build_lang_kb() -> InlineKeyboardMarkup:
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


# ---------- core router ----------
def build_router(db: Database, seedream: SeedreamService) -> Router:
    """
    Primary router:
    - базовые команды: start/help/profile
    - пополнение звёздами /buy
    - мультиязычность /language
    - доменные команды: /generate, /examples, /cancel
    """
    r = Router()
    r.message.middleware(PaymentGuard())
    pay = StarsPay(db)
    

    # --- /start ---
    @r.message(Command("start"))
    async def cmd_start(m: Message):
        async with db.session() as s:
            await upsert_user_basic(
                s,
                user_id=m.from_user.id,
                tg_username=m.from_user.username,
                lang=m.from_user.language_code,
                last_seen_at=datetime.now(timezone.utc),
                is_premium=getattr(m.from_user, "is_premium", False),
                is_bot=m.from_user.is_bot,
            )
        lang = await get_lang(m, db)
        await m.answer(f"<b>{T(lang, 'start_title')}</b>\n{T(lang, 'start_desc')}")

    # --- /help ---

    @r.message(Command("help"))
    async def cmd_help(m: Message):
        lang = await get_lang(m, db)
        items = phrases[lang]["help_items"]
        lines = [f"<b>{T(lang, 'help_header')}</b>"]
        for cmd, desc in items.items():
            lines.append(f"/{cmd} — {desc}")
        await m.answer("\n".join(lines))

    # --- /profile ---

    @r.message(Command("profile"))
    async def cmd_profile(m: Message):
        lang = await get_lang(m, db)
        async with db.session() as s:
            prof = await get_profile(s, tg_user_id=m.from_user.id)

        if not prof.user:
            await m.answer(T(lang, "profile_not_found"))
            return

        u = prof.user
        text = "\n".join(
            [
                f"<b>{T(lang, 'profile_title')}</b>",
                T(lang, "profile_line_id", user_id=u.user_id),
                T(lang, "profile_line_user", username=u.tg_username or "-"),
                T(lang, "profile_line_lang", lang=u.lang or "-"),
                T(
                    lang,
                    "profile_line_created",
                    created=str(u.created_at) if u.created_at else "-",
                ),
                T(
                    lang,
                    "profile_line_last_seen",
                    last_seen=str(u.last_seen_at) if u.last_seen_at else "-",
                ),
                T(
                    lang,
                    "profile_line_txn",
                    count=prof.txn_count,
                    sum=prof.txn_sum,
                    cur=prof.currency,
                ),
                T(
                    lang,
                    "profile_line_balance_credits",
                    balance=prof.credits_balance,
                ),
                T(
                    lang,
                    "profile_line_balance_money",
                    balance=prof.money_balance,
                ),
            ]
        )
        await m.answer(text)

    # --- /buy (пополнение звездами) ---

    @r.message(Command("buy"))
    async def cmd_buy(m: Message, state: FSMContext):
        lang = await get_lang(m, db)
        await pay.send_invoice(
            m,
            state=state,
            title=T(lang, "invoice_title"),
            desc=T(lang, "invoice_desc"),
            stars=1,
            payload=f"demo:{m.from_user.id}",
        )

    # --- /language (и /lang, /swith_lang для совместимости) ---

    @r.message(Command("language", "lang", "swith_lang"))
    async def cmd_switch_lang(m: Message):
        lang = await get_lang(m, db)
        await m.answer(T(lang, "choose_lang_title"), reply_markup=_build_lang_kb())

    @r.callback_query(F.data.startswith("set_lang:"))
    async def on_set_lang(q: CallbackQuery, bot: Bot):
        parts = q.data.split(":", 1)
        if len(parts) != 2:
            await q.answer("Oops")
            return

        new_lang = parts[1]
        if new_lang not in phrases:
            lang = await get_lang(q, db)
            await q.answer(T(lang, "unknown_lang"), show_alert=True)
            return

        # Persist language
        async with db.session() as s:
            await upsert_user_basic(
                s,
                user_id=q.from_user.id,
                tg_username=q.from_user.username,
                lang=new_lang,
                last_seen_at=datetime.now(timezone.utc),
                is_premium=getattr(q.from_user, "is_premium", False),
                is_bot=q.from_user.is_bot,
            )

        # Acknowledge + edit original message with confirmation in the selected language
        await q.answer("OK")
        try:
            await q.message.edit_text(
                T(new_lang, "lang_switched", lang=_lang_display_name(new_lang))
            )
        except Exception:
            # if message can't be edited (e.g., no rights), just send a new one
            await bot.send_message(
                chat_id=q.message.chat.id,
                text=T(
                    new_lang,
                    "lang_switched",
                    lang=_lang_display_name(new_lang),
                ),
            )

    # --- /examples ---

    @r.message(Command("examples"))
    async def cmd_examples(m: Message):
        lang = await get_lang(m, db)
        await m.answer(T(lang, "examples_soon"))

    # --- /cancel ---

    @r.message(Command("cancel"))
    async def cmd_cancel(m: Message, state: FSMContext):
        await state.clear()
        lang = await get_lang(m, db)
        await m.answer(T(lang, "cancel_done"))

    # --- /generate: заглушка под будущий конструктор генерации ---
    @r.message(Command("generate"))
    async def cmd_generate(m: Message, state: FSMContext):
        """
        Старт генерации:
        - проверяем/создаём пользователя
        - проверяем, что у пользователя есть минимум 1 кредит
        - показываем краткое описание + кнопку «Начать»
        """
        lang = await get_lang(m, db)

        async with db.session() as s:
            user = await upsert_user_basic(
                s,
                user_id=m.from_user.id,
                tg_username=m.from_user.username,
                lang=m.from_user.language_code,
                last_seen_at=datetime.now(timezone.utc),
                is_premium=getattr(m.from_user, "is_premium", False),
                is_bot=m.from_user.is_bot,
            )
            balance = int(user.credits_balance or 0)

        if balance < GEN_SCENARIO_PRICES["initial_generation"]:
            await m.answer(T(lang, "no_credits"))
            return

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_start"),
                        callback_data="gen:start",
                    )
                ]
            ]
        )

        await state.clear()
        sent = await m.answer(T(lang, "generate_intro_short"), reply_markup=kb)
        await state.update_data(
            generate_prompt_msg_id=sent.message_id,
            generate_chat_id=sent.chat.id,
        )


    # --- gen:start: показать рекомендации и выбор типа фото ---
    @r.callback_query(F.data == "gen:start")
    async def on_gen_start(q: CallbackQuery, state: FSMContext):
        from fsm import GenerationFlow

        lang = await get_lang(q, db)

        # переводим в состояние выбора типа
        await state.set_state(GenerationFlow.selecting_upload_type)

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_upload_flat"),
                        callback_data="gen:type:flat",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_upload_on_person"),
                        callback_data="gen:type:on_person",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_upload_on_mannequin"),
                        callback_data="gen:type:mannequin",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_back"),
                        callback_data="gen:back_to_intro",
                    )
                ],
            ]
        )

        await q.answer()
        try:
            await q.message.edit_text(
                T(lang, "upload_intro_full"),
                reply_markup=kb,
            )
        except Exception:
            # если не получилось отредактировать, просто отправим новое
            await q.message.answer(T(lang, "upload_intro_full"), reply_markup=kb)

        # гарантируем, что id текущего сообщения сохранён
        await state.update_data(
            generate_prompt_msg_id=q.message.message_id,
            generate_chat_id=q.message.chat.id,
        )


    # --- выбор типа загружаемой фотографии ---

    @r.callback_query(F.data.startswith("gen:type:"))
    async def on_gen_choose_type(q: CallbackQuery, state: FSMContext):
        from fsm import GenerationFlow

        current = await state.get_state()
        if current != GenerationFlow.selecting_upload_type.state:
            await q.answer()
            return

        lang = await get_lang(q, db)
        _, _, payload = q.data.partition("gen:type:")
        upload_type = payload or "flat"

        if upload_type == "flat":
            text_key = "prompt_upload_flat"
        elif upload_type == "on_person":
            text_key = "prompt_upload_on_person"
        else:
            text_key = "prompt_upload_on_mannequin"

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_back"),
                        callback_data="gen:back_to_types",
                    )
                ]
            ]
        )

        await q.answer()
        try:
            await q.message.edit_text(
                T(lang, text_key),
                reply_markup=kb,
            )
        except Exception:
            await q.message.answer(T(lang, text_key), reply_markup=kb)

        await state.update_data(
            generate_prompt_msg_id=q.message.message_id,
            generate_chat_id=q.message.chat.id,
            upload_type=upload_type,
        )
        await state.set_state(GenerationFlow.waiting_document)


    @r.callback_query(F.data == "gen:back_to_types")
    async def on_gen_back_to_types(q: CallbackQuery, state: FSMContext):
        from fsm import GenerationFlow

        lang = await get_lang(q, db)

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_upload_flat"),
                        callback_data="gen:type:flat",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_upload_on_person"),
                        callback_data="gen:type:on_person",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_upload_on_mannequin"),
                        callback_data="gen:type:mannequin",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_back"),
                        callback_data="gen:back_to_intro",
                    )
                ],
            ]
        )

        await q.answer()
        try:
            await q.message.edit_text(
                T(lang, "upload_intro_full"),
                reply_markup=kb,
            )
        except Exception:
            await q.message.answer(T(lang, "upload_intro_full"), reply_markup=kb)

        await state.set_state(GenerationFlow.selecting_upload_type)


    @r.callback_query(F.data == "gen:back_to_intro")
    async def on_gen_back_to_intro(q: CallbackQuery, state: FSMContext):
        """
        Возврат к самому первому экрану /generate.
        """
        lang = await get_lang(q, db)

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_start"),
                        callback_data="gen:start",
                    )
                ]
            ]
        )

        await q.answer()
        try:
            await q.message.edit_text(
                T(lang, "generate_intro_short"),
                reply_markup=kb,
            )
        except Exception:
            await q.message.answer(T(lang, "generate_intro_short"), reply_markup=kb)

        await state.clear()


    # --- Обработчик фото в рамках сценария генерации ---
    @r.message(F.photo)
    async def on_photo_for_generation(m: Message, state: FSMContext):
        """
        Если ждём документ, но приходит photo — просим юзера отправить как документ.
        Заодно логируем тип сообщения.
        """
        from fsm import GenerationFlow

        current_state = await state.get_state()
        # Логируем тип сообщения, чтобы ты видел в консоли
        logger.info(
            "Incoming message from %s: content_type=%s, media_group_id=%s",
            m.from_user.id,
            m.content_type,
            getattr(m, "media_group_id", None),
        )

        if current_state != GenerationFlow.waiting_document.state:
            # Фото не в контексте генерации — ничего не делаем
            return

        lang = await get_lang(m, db)
        await m.answer(T(lang, "upload_doc_only"))


    # --- Обработчик изображения-документа в рамках генерации ---
    @r.message(F.document)
    async def on_document_for_generation(m: Message, state: FSMContext):
        """
        Принимаем 1 фото одежды в виде документа.
        Сценарий >1 фото пока заглушка.
        После первого валидного документа сразу переходим к выбору фона.
        """
        from fsm import GenerationFlow

        current_state = await state.get_state()
        if current_state != GenerationFlow.waiting_document.state:
            # Документ пришёл не в контексте генерации
            return

        lang = await get_lang(m, db)
        data = await state.get_data()

        # Заглушка на сценарий с несколькими фото
        num_items = int(data.get("num_items") or 0)
        if num_items >= 1:
            await m.answer(T(lang, "multi_items_not_supported"))
            return

        doc = m.document
        mime = (doc.mime_type or "").lower()
        logger.info(
            "Incoming document from %s: mime=%s, file_id=%s",
            m.from_user.id,
            mime,
            doc.file_id,
        )

        if not mime.startswith("image/"):
            await m.answer(T(lang, "upload_doc_wrong_type"))
            return

        # Сохраняем в стейт только file_id – байты докачаем перед генерацией
        upload_type = data.get("upload_type") or "flat"
        await state.update_data(
            cloth_file_ids=[doc.file_id],
            num_items=1,
            upload_type=upload_type,
            backgrounds=[],
            gender=None,
            hair_color=None,
            age=None,
            style=None,
            aspect_ratios=[],
        )

        # Формируем текст шага про фон
        intro_text = T(lang, "settings_intro_single", count=1)
        bg_text = T(lang, "background_select_single")

        full_text = intro_text + "\n\n" + bg_text

        # Показываем выбор фона НОВЫМ сообщением
        kb = build_background_keyboard(lang, selected=set())
        sent = await m.answer(full_text, reply_markup=kb)

        # Обновляем "рабочее" сообщение для дальнейших редактирований
        await state.update_data(
            generate_prompt_msg_id=sent.message_id,
            generate_chat_id=sent.chat.id,
        )

        await state.set_state(GenerationFlow.choosing_background)


    @r.callback_query(F.data == "gen:back_to_background")
    async def on_gen_back_to_background(q: CallbackQuery, state: FSMContext):
        """
        Возврат со шага выбора пола обратно к выбору фона.
        """
        from fsm import GenerationFlow

        lang = await get_lang(q, db)
        data = await state.get_data()

        selected = set(data.get("backgrounds") or [])
        intro_text = T(lang, "settings_intro_single", count=data.get("num_items") or 1)
        base_text = T(lang, "background_select_single")

        if selected:
            labels = [
                T(lang, f"bg_label_{key}")
                for key in BG_KEYS
                if key in selected
            ]
            selected_block = (
                T(lang, "background_selected_header")
                + "\n"
                + "\n".join(labels)
            )
            full_text = intro_text + "\n\n" + base_text + "\n\n" + selected_block
        else:
            full_text = intro_text + "\n\n" + base_text

        kb = build_background_keyboard(lang, selected)

        try:
            await q.message.edit_text(full_text, reply_markup=kb)
        except Exception:
            await q.message.edit_caption(full_text, reply_markup=kb)

        await state.set_state(GenerationFlow.choosing_background)
        await q.answer()


    @r.callback_query(F.data.startswith("gen:bg:"))
    async def on_gen_choose_background(q: CallbackQuery, state: FSMContext):
        """
        Мультивыбор фона:
        - gen:bg:white|beige|pink|black — тогаем выбранность с галочками
        - gen:bg:next — сохраняем выбор и переходим к выбору пола
        """
        from fsm import GenerationFlow

        current_state = await state.get_state()
        if current_state != GenerationFlow.choosing_background.state:
            await q.answer()
            return

        lang = await get_lang(q, db)
        data = await state.get_data()
        prompt_msg_id = data.get("generate_prompt_msg_id") or q.message.message_id
        prompt_chat_id = data.get("generate_chat_id") or q.message.chat.id

        # Текущее множество выбранных фонов
        selected = set(data.get("backgrounds") or [])

        _, _, action = q.data.split(":", 2)

        # --- переключение конкретного цвета ---
        if action in BG_KEYS:
            if action in selected:
                selected.remove(action)
            else:
                selected.add(action)

            await state.update_data(backgrounds=list(selected))

            # Пересобираем текст
            intro_text = T(lang, "settings_intro_single", count=data.get("num_items") or 1)
            base_text = T(lang, "background_select_single")

            if selected:
                # Читаемые названия выбранных фонов
                labels = []
                for key in BG_KEYS:
                    if key in selected:
                        labels.append(T(lang, f"bg_label_{key}"))
                selected_block = (
                    T(lang, "background_selected_header")
                    + "\n"
                    + "\n".join(labels)
                )
                full_text = intro_text + "\n\n" + base_text + "\n\n" + selected_block
            else:
                full_text = intro_text + "\n\n" + base_text

            kb = build_background_keyboard(lang, selected)

            try:
                await q.message.edit_text(full_text, reply_markup=kb)
            except Exception:
                await q.message.edit_caption(full_text, reply_markup=kb)

            await q.answer()
            return

        # --- Next: идём к выбору пола ---
        if action == "next":
            if not selected:
                # Не даём уйти дальше без хотя бы одного цвета
                await q.answer(T(lang, "background_need_one"), show_alert=True)
                return

            # Сохраняем список фонов + "основной" (первый) для дальнейшего использования
            main_bg = next(iter(selected))
            await state.update_data(
                backgrounds=list(selected),
                background=main_bg,
            )

            # Переход к выбору пола (редактируем текущее сообщение)
            gender_text = T(lang, "gender_choose_title")
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=T(lang, "btn_gender_female"),
                            callback_data="gen:gender:female",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text=T(lang, "btn_gender_male"),
                            callback_data="gen:gender:male",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text=T(lang, "btn_back"),
                            callback_data="gen:back_to_background",
                        )
                    ],
                ]
            )

            try:
                await q.message.edit_text(gender_text, reply_markup=kb)
            except Exception:
                await q.message.edit_caption(gender_text, reply_markup=kb)

            await state.set_state(GenerationFlow.choosing_gender)
            await q.answer()
            return

        await q.answer()


    @r.callback_query(F.data.startswith("gen:gender:"))
    async def on_gen_choose_gender(q: CallbackQuery, state: FSMContext):
        """
        Выбор пола модели. Пока просто сохраняем в стейт и показываем заглушку.
        Дальнейшие шаги (волосы, возраст, стиль, соотношение сторон) добавим отдельно.
        """
        from fsm import GenerationFlow

        current_state = await state.get_state()
        if current_state != GenerationFlow.choosing_gender.state:
            await q.answer()
            return

        lang = await get_lang(q, db)
        _, _, gender = q.data.split(":", 2)
        if gender not in ("female", "male"):
            await q.answer()
            return

        await state.update_data(gender=gender)

        # На этом шаге просто подтверждаем выбор и гасим стейт.
        # На следующем шаге будем вести пользователя дальше (волосы и т.д.).
        await q.message.edit_text(T(lang, "gender_selected_stub"))
        await state.clear()
        await q.answer()


    @r.callback_query(F.data.startswith("gen:hair:"))
    async def on_gen_choose_hair(q: CallbackQuery, state: FSMContext):
        from fsm import GenerationFlow

        current = await state.get_state()
        if current != GenerationFlow.choosing_hair.state:
            await q.answer()
            return

        lang = await get_lang(q, db)
        _, _, hair = q.data.partition("gen:hair:")
        if hair not in ("any", "dark", "light"):
            await q.answer()
            return

        await state.update_data(hair=hair)

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_age_young"),
                        callback_data="gen:age:young",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_age_senior"),
                        callback_data="gen:age:senior",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_age_child"),
                        callback_data="gen:age:child",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_age_teen"),
                        callback_data="gen:age:teen",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_back"),
                        callback_data="gen:gender:female",  # формальный "back", упростим
                    )
                ],
            ]
        )

        try:
            await q.message.edit_text(
                T(lang, "settings_age_title"),
                reply_markup=kb,
            )
        except Exception:
            await q.message.answer(
                T(lang, "settings_age_title"),
                reply_markup=kb,
            )

        await state.set_state(GenerationFlow.choosing_age)
        await q.answer()


    @r.callback_query(F.data.startswith("gen:age:"))
    async def on_gen_choose_age(q: CallbackQuery, state: FSMContext):
        from fsm import GenerationFlow

        current = await state.get_state()
        if current != GenerationFlow.choosing_age.state:
            await q.answer()
            return

        lang = await get_lang(q, db)
        _, _, age = q.data.partition("gen:age:")
        if age not in ("young", "senior", "child", "teen"):
            await q.answer()
            return

        await state.update_data(age=age)

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_style_strict"),
                        callback_data="gen:style:strict",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_style_luxury"),
                        callback_data="gen:style:luxury",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_style_casual"),
                        callback_data="gen:style:casual",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_style_sport"),
                        callback_data="gen:style:sport",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_back"),
                        callback_data="gen:hair:any",
                    )
                ],
            ]
        )

        try:
            await q.message.edit_text(
                T(lang, "settings_style_title"),
                reply_markup=kb,
            )
        except Exception:
            await q.message.answer(
                T(lang, "settings_style_title"),
                reply_markup=kb,
            )

        await state.set_state(GenerationFlow.choosing_style)
        await q.answer()


    @r.callback_query(F.data.startswith("gen:style:"))
    async def on_gen_choose_style(q: CallbackQuery, state: FSMContext):
        from fsm import GenerationFlow

        current = await state.get_state()
        if current != GenerationFlow.choosing_style.state:
            await q.answer()
            return

        lang = await get_lang(q, db)
        _, _, style = q.data.partition("gen:style:")
        if style not in ("strict", "luxury", "casual", "sport"):
            await q.answer()
            return

        await state.update_data(style=style)

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_aspect_3_4"),
                        callback_data="gen:aspect:3_4",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_aspect_9_16"),
                        callback_data="gen:aspect:9_16",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_aspect_1_1"),
                        callback_data="gen:aspect:1_1",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_aspect_16_9"),
                        callback_data="gen:aspect:16_9",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_back"),
                        callback_data="gen:age:young",
                    )
                ],
            ]
        )

        try:
            await q.message.edit_text(
                T(lang, "settings_aspect_title"),
                reply_markup=kb,
            )
        except Exception:
            await q.message.answer(
                T(lang, "settings_aspect_title"),
                reply_markup=kb,
            )

        await state.set_state(GenerationFlow.choosing_aspect)
        await q.answer()


    @r.callback_query(F.data.startswith("gen:aspect:"))
    async def on_gen_choose_aspect(q: CallbackQuery, state: FSMContext):
        from fsm import GenerationFlow

        current = await state.get_state()
        if current != GenerationFlow.choosing_aspect.state:
            await q.answer()
            return

        lang = await get_lang(q, db)
        _, _, aspect = q.data.partition("gen:aspect:")
        if aspect not in ("3_4", "9_16", "1_1", "16_9"):
            await q.answer()
            return

        await state.update_data(aspect=aspect)

        # --- формируем summary ---
        data = await state.get_data()
        num_items = int(data.get("num_items") or 1)
        bg_key = data.get("background") or "white"
        gender = data.get("gender") or "female"
        hair = data.get("hair") or "any"
        age = data.get("age") or "young"
        style = data.get("style") or "casual"

        # читаем баланс
        async with db.session() as s:
            prof = await get_profile(s, tg_user_id=q.from_user.id)
            balance = prof.credits_balance

        # пока генерируем по одному фото
        photos = num_items  # в будущем сюда войдёт произведение выборов

        # локализованные подписи
        if lang == "ru":
            bg_label = BG_LABELS[bg_key][0]
            gender_label = GENDER_LABELS[gender][0]
            hair_label = HAIR_LABELS[hair][0]
            age_label = AGE_LABELS[age][0]
            style_label = STYLE_LABELS[style][0]
            aspect_label = ASPECT_LABELS[aspect][0]
        else:
            bg_label = BG_LABELS[bg_key][1]
            gender_label = GENDER_LABELS[gender][1]
            hair_label = HAIR_LABELS[hair][1]
            age_label = AGE_LABELS[age][1]
            style_label = STYLE_LABELS[style][1]
            aspect_label = ASPECT_LABELS[aspect][1]

        base_text = T(
            lang,
            "confirm_generation_title",
            items=num_items,
            background=bg_label,
            gender=gender_label,
            hair=hair_label,
            age=age_label,
            style=style_label,
            aspect=aspect_label,
            balance=balance,
            photos=photos,
        )

        extra_text = (
            "\n\n" + T(lang, "confirm_generation_ok")
            if balance >= photos
            else "\n\n" + T(lang, "confirm_generation_not_enough")
        )

        kb_buttons = [
            [
                InlineKeyboardButton(
                    text=T(lang, "btn_confirm_next"),
                    callback_data="gen:confirm:next",
                )
            ]
        ]
        if balance < photos:
            kb_buttons.append(
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_confirm_topup"),
                        callback_data="gen:confirm:topup",
                    )
                ]
            )
        kb_buttons.append(
            [
                InlineKeyboardButton(
                    text=T(lang, "btn_back"),
                    callback_data="gen:aspect_back",
                )
            ]
        )

        kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)

        try:
            await q.message.edit_text(base_text + extra_text, reply_markup=kb)
        except Exception:
            await q.message.answer(base_text + extra_text, reply_markup=kb)

        await state.set_state(GenerationFlow.confirming)
        await q.answer()


    @r.callback_query(F.data.startswith("gen:confirm:"))
    async def on_gen_confirm(q: CallbackQuery, state: FSMContext):
        """
        Подтверждение генерации:
        - проверяем баланс
        - собираем промпт из выбранных параметров
        - создаём Generation + списываем кредиты
        - вызываем Seedream API, ждём результат, сохраняем в БД и отправляем фото
        """
        from fsm import GenerationFlow
        from db import GeneratedImage, ImageRole  # локальный импорт

        current = await state.get_state()
        if current != GenerationFlow.confirming.state:
            await q.answer()
            return

        lang = await get_lang(q, db)
        action = q.data.split(":", 2)[-1]

        if action == "topup":
            # просто подсказка про /buy
            await q.answer()
            await q.message.answer(T(lang, "no_credits"))
            return

        if action != "next":
            await q.answer()
            return

        data = await state.get_data()
        cloth_urls = data.get("cloth_urls") or []
        if not cloth_urls:
            await q.answer()
            await q.message.answer(T(lang, "generation_failed"))
            await state.clear()
            return

        cloth_url = cloth_urls[0]
        upload_type = data.get("upload_type") or "flat"

        bg_key = data.get("background") or "white"
        gender = data.get("gender") or "female"
        hair = data.get("hair") or "any"
        age = data.get("age") or "young"
        style = data.get("style") or "casual"
        aspect = data.get("aspect") or "3_4"

        # мапим в сниппеты
        background_snippet = BG_SNIPPETS[bg_key]
        hair_snippet = HAIR_SNIPPETS[hair]
        age_snippet = AGE_SNIPPETS[age]
        style_snippet = STYLE_SNIPPETS[style]
        image_size, image_resolution = ASPECT_PARAMS[aspect]

        # считаем, сколько фото планируем (пока = 1 * items)
        num_items = int(data.get("num_items") or 1)
        total_images_planned = num_items  # на будущее можно расширить

        # проверяем баланс и создаём Generation
        async with db.session() as s:
            gen_obj, user, price = await ensure_credits_and_create_generation(
                s,
                tg_user_id=q.from_user.id,
                prompt=seedream.build_ecom_prompt(
                    gender=gender,
                    hair_color=hair_snippet,
                    age=age_snippet,
                    style_snippet=style_snippet,
                    background_snippet=background_snippet,
                ),
                scenario_key="initial_generation",
                total_images_planned=total_images_planned,
                params={
                    "scenario": "initial_generation",
                    "upload_type": upload_type,
                    "gender": gender,
                    "hair": hair,
                    "age": age,
                    "style": style,
                    "background": bg_key,
                    "aspect": aspect,
                    "image_size": image_size,
                    "image_resolution": image_resolution,
                },
                source_image_urls=[cloth_url],
            )

            if gen_obj is None:
                # кредитов не хватило
                await state.clear()
                await q.answer()
                try:
                    await q.message.edit_text(T(lang, "no_credits"))
                except Exception:
                    await q.message.answer(T(lang, "no_credits"))
                return

            generation_id = gen_obj.id

        # промпт ещё раз, уже для API
        prompt = seedream.build_ecom_prompt(
            gender=gender,
            hair_color=hair_snippet,
            age=age_snippet,
            style_snippet=style_snippet,
            background_snippet=background_snippet,
        )

        # обновляем текст: задача в обработке
        try:
            await q.message.edit_text(T(lang, "processing_generation"))
        except Exception:
            await q.message.answer(T(lang, "processing_generation"))

        # создаём задачу Seedream
        try:
            task_id = await asyncio.to_thread(
                seedream.create_task,
                prompt,
                image_size=image_size,
                image_resolution=image_resolution,
                max_images=total_images_planned,
                image_urls=[cloth_url],
            )
        except Exception as e:
            # откат статуса и возврат кредитов
            async with db.session() as s:
                gen_db: Optional[Generation] = (
                    await s.execute(
                        select(Generation).where(Generation.id == generation_id)
                    )
                ).scalar_one_or_none()
                user_db: Optional[User] = (
                    await s.execute(
                        select(User).where(User.user_id == q.from_user.id)
                    )
                ).scalar_one_or_none()

                if gen_db:
                    gen_db.status = GenerationStatus.failed
                    gen_db.error_message = str(e)
                if user_db and gen_db:
                    user_db.credits_balance = (user_db.credits_balance or 0) + gen_db.credits_spent

            await state.clear()
            err_text = T(lang, "generation_failed")
            try:
                await q.message.edit_text(err_text)
            except Exception:
                await q.message.answer(err_text)
            logger.exception("Seedream create_task failed", exc_info=e)
            await q.answer()
            return

        # обновляем Generation: external_id + статус running
        async with db.session() as s:
            gen_db: Optional[Generation] = (
                await s.execute(
                    select(Generation).where(Generation.id == generation_id)
                )
            ).scalar_one_or_none()
            if gen_db:
                gen_db.external_id = task_id
                gen_db.status = GenerationStatus.running

        # уведомляем пользователя, что задача в очереди
        notify_text = T(lang, "task_queued", task_id=task_id)
        try:
            await q.message.edit_text(notify_text)
        except Exception:
            await q.message.answer(notify_text)

        # ждём результат, скачиваем картинки
        try:
            task_info = await asyncio.to_thread(
                seedream.wait_for_result,
                task_id,
                poll_interval=5.0,
                timeout=180.0,
            )
            data_info = task_info.get("data", {})
            result_json_str = data_info.get("resultJson")
            if not result_json_str:
                raise RuntimeError(f"No resultJson in task_info={task_info!r}")

            result_obj = json.loads(result_json_str)
            result_urls = result_obj.get("resultUrls") or []
            if not result_urls:
                raise RuntimeError(f"No resultUrls in resultJson={result_obj!r}")

            image_bytes_list: list[tuple[str, bytes]] = []
            for url in result_urls:
                download_url = await asyncio.to_thread(seedream.get_download_url, url)
                img_bytes = await asyncio.to_thread(
                    seedream.download_file_bytes, download_url
                )
                image_bytes_list.append((url, img_bytes))

        except Exception as e:
            # mark failed, return credits
            async with db.session() as s:
                gen_db: Optional[Generation] = (
                    await s.execute(
                        select(Generation).where(Generation.id == generation_id)
                    )
                ).scalar_one_or_none()
                user_db: Optional[User] = (
                    await s.execute(
                        select(User).where(User.user_id == q.from_user.id)
                    )
                ).scalar_one_or_none()

                if gen_db:
                    gen_db.status = GenerationStatus.failed
                    gen_db.error_message = str(e)
                if user_db and gen_db:
                    user_db.credits_balance = (user_db.credits_balance or 0) + gen_db.credits_spent

            await state.clear()
            err_text = T(lang, "generation_failed")
            try:
                await q.message.edit_text(err_text)
            except Exception:
                await q.message.answer(err_text)
            logger.exception("Seedream wait_for_result/download failed", exc_info=e)
            await q.answer()
            return

        # сохраняем результат в БД
        async with db.session() as s:
            gen_db: Optional[Generation] = (
                await s.execute(
                    select(Generation).where(Generation.id == generation_id)
                )
            ).scalar_one_or_none()

            if gen_db:
                gen_db.status = GenerationStatus.succeeded
                gen_db.images_generated = len(result_urls)
                gen_db.finished_at = datetime.now(timezone.utc)

                for url, _bytes in image_bytes_list:
                    img = GeneratedImage(
                        generation_id=gen_db.id,
                        user_id=q.from_user.id,
                        role=ImageRole.base,
                        storage_url=url,
                        telegram_file_id=None,
                        width=None,
                        height=None,
                        meta={
                            "scenario": "initial_generation",
                            "upload_type": upload_type,
                            "gender": gender,
                            "hair": hair,
                            "age": age,
                            "style": style,
                            "background": bg_key,
                            "aspect": aspect,
                        },
                    )
                    s.add(img)

        # отправляем пользователю первую картинку
        from aiogram.types import BufferedInputFile

        first_url, first_bytes = image_bytes_list[0]
        sent_photo = await q.message.answer_photo(
            photo=BufferedInputFile(first_bytes, filename="seedream_initial.png"),
            caption=T(lang, "generation_done"),
        )

        # обновляем telegram_file_id для первой картинки
        async with db.session() as s:
            first_img: Optional[GeneratedImage] = (
                await s.execute(
                    select(GeneratedImage)
                    .where(
                        GeneratedImage.generation_id == generation_id,
                        GeneratedImage.user_id == q.from_user.id,
                    )
                    .order_by(GeneratedImage.id.asc())
                )
            ).scalars().first()

            if first_img and sent_photo.photo:
                first_img.telegram_file_id = sent_photo.photo[-1].file_id

        await state.clear()

        try:
            await q.message.edit_text(T(lang, "generation_done"))
        except Exception:
            pass

        await q.answer()


    # --- payments flow ---
    @r.pre_checkout_query()
    async def on_pre_checkout(q: PreCheckoutQuery):
        await pay.pre_checkout_handler(q)

    @r.message(F.successful_payment)
    async def on_success_payment(m: Message, state: FSMContext):
        await pay.on_successful_payment(m, state)
    
    # --- debug: логируем тип каждого входящего сообщения ---
    @r.message()
    async def debug_message_types(m: Message):
        logger.info(
            "Incoming message",
            extra={
                "user_id": m.from_user.id if m.from_user else None,
                "content_type": m.content_type,
                "has_text": bool(m.text),
                "has_photo": bool(m.photo),
                "has_document": bool(m.document),
                "has_successful_payment": bool(m.successful_payment),
            },
        )


    return r
