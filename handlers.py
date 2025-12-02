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


# ---------- core router ----------


def build_router(db: Database) -> Router:
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
    async def cmd_generate(m: Message):
        """
        Стартовый entrypoint для генераций.
        Сейчас делает только запись Generation в БД (заглушка вместо вызова Seedream).
        Дальше можно навесить FSM и конструктор шагов.
        """
        lang = await get_lang(m, db)

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

            gen: Generation = await create_generation(
                s,
                user_id=m.from_user.id,
                prompt="STUB: generation flow not implemented yet",
                model_name="seedream-4.0",
                params={"source": "command_generate"},
                source_image_urls=None,
                total_images_planned=0,
                credits_spent=0,
                status=GenerationStatus.queued,
                external_id=None,
            )
            # Чтобы id гарантированно был доступен до выхода из контекста
            await s.flush()

            gen_id = gen.id

        await m.answer(T(lang, "generate_stub_registered", gen_id=gen_id))

    # --- payments flow ---

    @r.pre_checkout_query()
    async def on_pre_checkout(q: PreCheckoutQuery):
        await pay.pre_checkout_handler(q)

    @r.message(F.successful_payment)
    async def on_success_payment(m: Message, state: FSMContext):
        await pay.on_successful_payment(m, state)

    return r
