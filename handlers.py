# handlers.py
from __future__ import annotations
from aiogram.types import BufferedInputFile
from datetime import datetime, timezone
from typing import Optional, Any
from decimal import Decimal
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
    LabeledPrice,
    PreCheckoutQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fsm import AnyInput
from db import (
    Database,
    User,
    Transaction,
    TransactionKind,
    TransactionStatus,
    Generation,
    GenerationStatus,
    GeneratedImage,
    ImageRole,
    upsert_user_basic,
    record_transaction,
)
from yookassa_service import YooKassaService
from fsm import *
from seedream_service import SeedreamService
from yookassa_service import YooKassaService
from config import *
import asyncio
import json
from io import BytesIO
from text import phrases
# Import helper functions from modular structure
from handlers_func.i18n_helpers import get_lang, T, T_item, install_bot_commands
from handlers_func.db_helpers import Profile, get_profile, ensure_credits_and_create_generation
from handlers_func.keyboards import (
    build_lang_kb as _build_lang_kb,
    build_background_keyboard,
    build_hair_keyboard,
    build_style_keyboard,
    build_aspect_keyboard,
    _lang_display_name,
    build_main_keyboard,
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
    yookassa = YooKassaService()

    yookassa = YooKassaService()


    # --- /start ---
    @r.message(Command("start"))
    async def cmd_start(m: Message, state: FSMContext):
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
        await state.clear()  # Clear any existing state
        await m.answer(
            f"<b>{T(lang, 'start_title')}</b>\n{T(lang, 'start_desc')}",
            reply_markup=build_main_keyboard(lang)
        )
        await state.clear()  # Clear any existing state
        await m.answer(
            f"<b>{T(lang, 'start_title')}</b>\n{T(lang, 'start_desc')}",
            reply_markup=build_main_keyboard(lang)
        )

    # --- /help ---

    @r.message(Command("help"))
    async def cmd_help(m: Message):
        lang = await get_lang(m, db)
        items = phrases[lang]["help_items"]
        lines = [f"<b>{T(lang, 'help_header')}</b>"]
        for cmd, desc in items.items():
            lines.append(f"/{cmd} — {desc}")
        await m.answer("\n".join(lines))

    # --- /profile (now Account Menu) ---

    async def _show_account_menu(message: Message, lang: str):
        """Show the account menu with Balance and History buttons."""
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=T(lang, "btn_balance"), callback_data="account:balance")],
                [InlineKeyboardButton(text=T(lang, "btn_history"), callback_data="account:history:0")],
                [InlineKeyboardButton(text=T(lang, "btn_back"), callback_data="account:back")],
            ]
        )
        await message.answer(T(lang, "account_menu"), reply_markup=kb)

    async def _show_payment_method_selection(message: Message, lang: str):
        """Show payment method selection (Stars or YooKassa)."""
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=T(lang, "btn_pay_stars"), callback_data="pay:stars")],
                [InlineKeyboardButton(text=T(lang, "btn_pay_yookassa"), callback_data="pay:yookassa")],
            ]
        )
        text = f"{T(lang, 'payment_method_title')}\n\n{T(lang, 'payment_method_desc')}"
        await message.answer(text, reply_markup=kb)
    # --- /profile (now Account Menu) ---

    async def _show_account_menu(message: Message, lang: str):
        """Show the account menu with Balance and History buttons."""
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=T(lang, "btn_balance"), callback_data="account:balance")],
                [InlineKeyboardButton(text=T(lang, "btn_history"), callback_data="account:history:0")],
                [InlineKeyboardButton(text=T(lang, "btn_back"), callback_data="account:back")],
            ]
        )
        await message.answer(T(lang, "account_menu"), reply_markup=kb)

    async def _show_payment_method_selection(message: Message, lang: str):
        """Show payment method selection (Stars or YooKassa)."""
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=T(lang, "btn_pay_stars"), callback_data="pay:stars")],
                [InlineKeyboardButton(text=T(lang, "btn_pay_yookassa"), callback_data="pay:yookassa")],
            ]
        )
        text = f"{T(lang, 'payment_method_title')}\n\n{T(lang, 'payment_method_desc')}"
        await message.answer(text, reply_markup=kb)

    @r.message(Command("profile"))
    async def cmd_profile(m: Message):
        lang = await get_lang(m, db)
        await _show_account_menu(m, lang)

    # Handle keyboard button presses
    @r.message(F.text.in_([phrases["ru"]["kb_my_account"], phrases["en"]["kb_my_account"]]))
    async def on_my_account_button(m: Message):
        lang = await get_lang(m, db)
        await _show_account_menu(m, lang)

    @r.message(F.text.in_([phrases["ru"]["kb_generation"], phrases["en"]["kb_generation"]]))
    async def on_generation_button(m: Message, state: FSMContext):
        # Redirect to /generate command
        await cmd_generate(m, state)

    @r.message(F.text.in_([phrases["ru"]["kb_examples"], phrases["en"]["kb_examples"]]))
    async def on_examples_button(m: Message):
        # Redirect to /examples command
        await cmd_examples(m)

    # Account menu callbacks
    @r.callback_query(F.data == "account:back")
    async def on_account_back(q: CallbackQuery):
        await q.message.delete()
        await q.answer()

    # Handle keyboard button presses
    @r.message(F.text.in_([phrases["ru"]["kb_my_account"], phrases["en"]["kb_my_account"]]))
    async def on_my_account_button(m: Message):
        lang = await get_lang(m, db)
        await _show_account_menu(m, lang)

    @r.message(F.text.in_([phrases["ru"]["kb_generation"], phrases["en"]["kb_generation"]]))
    async def on_generation_button(m: Message, state: FSMContext):
        # Redirect to /generate command
        await cmd_generate(m, state)

    @r.message(F.text.in_([phrases["ru"]["kb_examples"], phrases["en"]["kb_examples"]]))
    async def on_examples_button(m: Message):
        # Redirect to /examples command
        await cmd_examples(m)

    # Account menu callbacks
    @r.callback_query(F.data == "account:back")
    async def on_account_back(q: CallbackQuery):
        await q.message.delete()
        await q.answer()

    @r.callback_query(F.data == "account:balance")
    async def on_account_balance(q: CallbackQuery):
        """Show balance view."""
        lang = await get_lang(q, db)

        async with db.session() as s:
            prof = await get_profile(s, tg_user_id=q.from_user.id)
            prof = await get_profile(s, tg_user_id=q.from_user.id)

        if not prof.user:
            await q.answer(T(lang, "profile_not_found"), show_alert=True)
            await q.answer(T(lang, "profile_not_found"), show_alert=True)
            return

        # Assuming 1 generation = 10 rubles (you can adjust this)
        PRICE_PER_GEN = 10

        text = (
            f"{T(lang, 'balance_title')}\n\n"
            f"{T(lang, 'balance_generations', count=prof.credits_balance)}\n"
            f"{T(lang, 'balance_rubles', amount=prof.money_balance)}\n"
            f"{T(lang, 'balance_price_per_gen', price=PRICE_PER_GEN)}"
        )

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=T(lang, "btn_topup"), callback_data="account:topup")],
                [InlineKeyboardButton(text=T(lang, "btn_back"), callback_data="account:menu")],
            ]
        )

        try:
            await q.message.edit_text(text, reply_markup=kb)
        except Exception:
            await q.message.answer(text, reply_markup=kb)
        await q.answer()

    @r.callback_query(F.data == "account:topup")
    async def on_account_topup(q: CallbackQuery, state: FSMContext):
        """Handle top-up request - show payment method selection."""
        lang = await get_lang(q, db)
        await _show_payment_method_selection(q.message, lang)
        await q.answer()

    @r.callback_query(F.data == "account:menu")
    async def on_account_menu(q: CallbackQuery):
        """Return to account menu."""
        lang = await get_lang(q, db)

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=T(lang, "btn_balance"), callback_data="account:balance")],
                [InlineKeyboardButton(text=T(lang, "btn_history"), callback_data="account:history:0")],
                [InlineKeyboardButton(text=T(lang, "btn_back"), callback_data="account:back")],
            ]
        )

        try:
            await q.message.edit_text(T(lang, "account_menu"), reply_markup=kb)
        except Exception:
            await q.message.answer(T(lang, "account_menu"), reply_markup=kb)
        await q.answer()

    @r.callback_query(F.data.startswith("account:history:"))
    async def on_account_history(q: CallbackQuery):
        """Show generation history with pagination."""
        lang = await get_lang(q, db)

        # Parse page number
        page = int(q.data.split(":")[-1])

        # Get history from database (last month)
        from datetime import timedelta
        one_month_ago = datetime.now(timezone.utc) - timedelta(days=30)

        async with db.session() as s:
            # Get successful generations from last month
            stmt = (
                select(Generation)
                .where(Generation.user_id == q.from_user.id)
                .where(Generation.status == GenerationStatus.succeeded)
                .where(Generation.finished_at >= one_month_ago)
                .order_by(Generation.finished_at.desc())
            )
            result = await s.execute(stmt)
            all_gens = result.scalars().all()

        if not all_gens:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=T(lang, "btn_back"), callback_data="account:menu")],
                ]
            )
            try:
                await q.message.edit_text(
                    f"{T(lang, 'history_title')}\n\n{T(lang, 'history_empty')}",
                    reply_markup=kb
                )
            except Exception:
                await q.message.answer(
                    f"{T(lang, 'history_title')}\n\n{T(lang, 'history_empty')}",
                    reply_markup=kb
                )
            await q.answer()
            return

        # Pagination
        ITEMS_PER_PAGE = 5
        total_pages = (len(all_gens) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        page = max(0, min(page, total_pages - 1))

        start_idx = page * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        page_gens = all_gens[start_idx:end_idx]

        # Build history text
        lines = [T(lang, "history_title"), ""]

        for gen in page_gens:
            # Combine date and time into one line
            datetime_str = gen.finished_at.strftime("%Y-%m-%d %H:%M:%S") if gen.finished_at else "N/A"

            # Format parameters from JSONB into readable text
            params_dict = gen.params or {}
            params_parts = []

            # Extract common parameters
            if "scenario" in params_dict:
                scenario = params_dict["scenario"]
                if scenario == "initial_generation":
                    params_parts.append(f"Scenario: Initial generation")
                elif scenario == "per_item_generation":
                    params_parts.append(f"Scenario: Per-item")

            if "action" in params_dict:
                action = params_dict["action"]
                action_names = {
                    "change_pose": "Change pose",
                    "change_angle": "Change angle",
                    "rear_view_no_ref": "Rear view",
                    "rear_view_with_ref": "Rear view (with reference)",
                    "full_body": "Full body",
                    "upper_body": "Upper body",
                    "lower_body": "Lower body",
                }
                params_parts.append(action_names.get(action, action))

            if "gender" in params_dict:
                params_parts.append(f"Gender: {params_dict['gender']}")
            if "age" in params_dict:
                params_parts.append(f"Age: {params_dict['age']}")
            if "background" in params_dict:
                params_parts.append(f"Background: {params_dict['background']}")
            if "hair" in params_dict and params_dict["hair"] != "any":
                params_parts.append(f"Hair: {params_dict['hair']}")
            if "style" in params_dict:
                params_parts.append(f"Style: {params_dict['style']}")
            if "aspect" in params_dict:
                params_parts.append(f"Aspect: {params_dict['aspect']}")

            params_str = ", ".join(params_parts) if params_parts else "N/A"

            item_text = T(
                lang,
                "history_item",
                datetime=datetime_str,
                cost=gen.credits_spent or 1,
                params=params_str,
            )
            lines.append(item_text)

            # Add buttons for this generation
            lines.append("")  # Spacing

        lines.append(f"\n{T(lang, 'history_page', page=page + 1, total=total_pages)}")
        lines.append(T(lang, "history_month_limit"))

        text = "\n".join(lines)

        # Build keyboard with pagination and download buttons
        kb_rows = []

        # Add download/use buttons for each generation on this page
        for i, gen in enumerate(page_gens):
            row = [
                InlineKeyboardButton(
                    text=f"{T(lang, 'btn_download')} #{start_idx + i + 1}",
                    callback_data=f"hist:download:{gen.id}"
                ),
                InlineKeyboardButton(
                    text=f"{T(lang, 'btn_use_as_base')} #{start_idx + i + 1}",
                    callback_data=f"hist:use_base:{gen.id}"
                ),
            ]
            kb_rows.append(row)

        # Pagination buttons
        nav_row = []
        if page > 0:
            nav_row.append(
                InlineKeyboardButton(text=T(lang, "btn_prev_page"), callback_data=f"account:history:{page - 1}")
            )
        if page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(text=T(lang, "btn_next_page"), callback_data=f"account:history:{page + 1}")
            )
        if nav_row:
            kb_rows.append(nav_row)

        # Back button
        kb_rows.append([InlineKeyboardButton(text=T(lang, "btn_back"), callback_data="account:menu")])

        kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

        try:
            await q.message.edit_text(text, reply_markup=kb)
        except Exception:
            await q.message.answer(text, reply_markup=kb)
        await q.answer()

    @r.callback_query(F.data.startswith("hist:download:"))
    async def on_history_download(q: CallbackQuery):
        """Download images from a generation."""
        lang = await get_lang(q, db)
        gen_id = int(q.data.split(":")[-1])

        async with db.session() as s:
            # Get generation and its images
            gen = (await s.execute(select(Generation).where(Generation.id == gen_id))).scalar_one_or_none()

            if not gen or gen.user_id != q.from_user.id:
                await q.answer("Generation not found", show_alert=True)
                return

            # Get images
            images = (
                await s.execute(
                    select(GeneratedImage).where(GeneratedImage.generation_id == gen_id)
                )
            ).scalars().all()

        if not images:
            await q.answer("No images found", show_alert=True)
            return

        await q.answer("Downloading...")

        # Download and send images
        for i, img in enumerate(images):
            try:
                # Download from storage_url
                img_bytes = await asyncio.to_thread(seedream.download_file_bytes, img.storage_url)

                # Send as document
                from aiogram.types import BufferedInputFile
                await q.message.answer_document(
                    document=BufferedInputFile(img_bytes, filename=f"generation_{gen_id}_{i + 1}.png"),
                    caption=f"Generation #{gen_id} - Image {i + 1}/{len(images)}"
                )
            except Exception as e:
                logger.exception(f"Failed to download image {img.id}", exc_info=e)

    @r.callback_query(F.data.startswith("hist:use_base:"))
    async def on_history_use_as_base(q: CallbackQuery, state: FSMContext):
        """Use a historical generation as base for angles/poses stage."""
        lang = await get_lang(q, db)
        gen_id = int(q.data.split(":")[-1])

        async with db.session() as s:
            # Get generation and its images
            gen = (await s.execute(select(Generation).where(Generation.id == gen_id))).scalar_one_or_none()

            if not gen or gen.user_id != q.from_user.id:
                await q.answer("Generation not found", show_alert=True)
                return

            # Get images
            images = (
                await s.execute(
                    select(GeneratedImage).where(GeneratedImage.generation_id == gen_id)
                )
            ).scalars().all()

        if not images:
            await q.answer("No images found", show_alert=True)
            return

        # Download image bytes for state
        img_bytes = await asyncio.to_thread(seedream.download_file_bytes, images[0].storage_url)

        # Initialize angles/poses stage with this as base photo
        base_photo = {
            "url": images[0].storage_url,
            "bytes": img_bytes,
            "generation_id": gen_id,
            "background": (gen.params or {}).get("background", "white"),
            "hair": (gen.params or {}).get("hair", "any"),
            "style": (gen.params or {}).get("style", "casual"),
            "aspect": (gen.params or {}).get("aspect", "3_4"),
        }

        await state.update_data(
            base_photos=[base_photo],
            current_base_index=0,
        )
        # Assuming 1 generation = 10 rubles (you can adjust this)
        PRICE_PER_GEN = 10

        async with db.session() as s:
            prof = await get_profile(s, tg_user_id=q.from_user.id)

        text = (
            f"{T(lang, 'balance_title')}\n\n"
            f"{T(lang, 'balance_generations', count=prof.credits_balance)}\n"
            f"{T(lang, 'balance_rubles', amount=prof.money_balance)}\n"
            f"{T(lang, 'balance_price_per_gen', price=PRICE_PER_GEN)}"
        )

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=T(lang, "btn_topup"), callback_data="account:topup")],
                [InlineKeyboardButton(text=T(lang, "btn_back"), callback_data="account:menu")],
            ]
        )

        try:
            await q.message.edit_text(text, reply_markup=kb)
        except Exception:
            await q.message.answer(text, reply_markup=kb)
        await q.answer()

    @r.callback_query(F.data == "account:topup")
    async def on_account_topup(q: CallbackQuery, state: FSMContext):
        """Handle top-up request - show payment method selection."""
        lang = await get_lang(q, db)
        await _show_payment_method_selection(q.message, lang)
        await q.answer()

    @r.callback_query(F.data == "account:menu")
    async def on_account_menu(q: CallbackQuery):
        """Return to account menu."""
        lang = await get_lang(q, db)

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=T(lang, "btn_balance"), callback_data="account:balance")],
                [InlineKeyboardButton(text=T(lang, "btn_history"), callback_data="account:history:0")],
                [InlineKeyboardButton(text=T(lang, "btn_back"), callback_data="account:back")],
            ]
        )

        try:
            await q.message.edit_text(T(lang, "account_menu"), reply_markup=kb)
        except Exception:
            await q.message.answer(T(lang, "account_menu"), reply_markup=kb)
        await q.answer()

    @r.callback_query(F.data.startswith("account:history:"))
    async def on_account_history(q: CallbackQuery):
        """Show generation history with pagination."""
        lang = await get_lang(q, db)

        # Parse page number
        page = int(q.data.split(":")[-1])

        # Get history from database (last month)
        from datetime import timedelta
        one_month_ago = datetime.now(timezone.utc) - timedelta(days=30)

        async with db.session() as s:
            # Get successful generations from last month
            stmt = (
                select(Generation)
                .where(Generation.user_id == q.from_user.id)
                .where(Generation.status == GenerationStatus.succeeded)
                .where(Generation.finished_at >= one_month_ago)
                .order_by(Generation.finished_at.desc())
            )
            result = await s.execute(stmt)
            all_gens = result.scalars().all()

        if not all_gens:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=T(lang, "btn_back"), callback_data="account:menu")],
                ]
            )
            try:
                await q.message.edit_text(
                    f"{T(lang, 'history_title')}\n\n{T(lang, 'history_empty')}",
                    reply_markup=kb
                )
            except Exception:
                await q.message.answer(
                    f"{T(lang, 'history_title')}\n\n{T(lang, 'history_empty')}",
                    reply_markup=kb
                )
            await q.answer()
            return

        # Pagination
        ITEMS_PER_PAGE = 5
        total_pages = (len(all_gens) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        page = max(0, min(page, total_pages - 1))

        start_idx = page * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        page_gens = all_gens[start_idx:end_idx]

        # Build history text
        lines = [T(lang, "history_title"), ""]

        for gen in page_gens:
            # Combine date and time into one line
            datetime_str = gen.finished_at.strftime("%Y-%m-%d %H:%M:%S") if gen.finished_at else "N/A"

            # Format parameters from JSONB into readable text
            params_dict = gen.params or {}
            params_parts = []

            # Extract common parameters
            if "scenario" in params_dict:
                scenario = params_dict["scenario"]
                if scenario == "initial_generation":
                    params_parts.append(f"Scenario: Initial generation")
                elif scenario == "per_item_generation":
                    params_parts.append(f"Scenario: Per-item")

            if "action" in params_dict:
                action = params_dict["action"]
                action_names = {
                    "change_pose": "Change pose",
                    "change_angle": "Change angle",
                    "rear_view_no_ref": "Rear view",
                    "rear_view_with_ref": "Rear view (with reference)",
                    "full_body": "Full body",
                    "upper_body": "Upper body",
                    "lower_body": "Lower body",
                }
                params_parts.append(action_names.get(action, action))

            if "gender" in params_dict:
                params_parts.append(f"Gender: {params_dict['gender']}")
            if "age" in params_dict:
                params_parts.append(f"Age: {params_dict['age']}")
            if "background" in params_dict:
                params_parts.append(f"Background: {params_dict['background']}")
            if "hair" in params_dict and params_dict["hair"] != "any":
                params_parts.append(f"Hair: {params_dict['hair']}")
            if "style" in params_dict:
                params_parts.append(f"Style: {params_dict['style']}")
            if "aspect" in params_dict:
                params_parts.append(f"Aspect: {params_dict['aspect']}")

            params_str = ", ".join(params_parts) if params_parts else "N/A"

            item_text = T(
                lang,
                "history_item",
                datetime=datetime_str,
                cost=gen.credits_spent or 1,
                params=params_str,
            )
            lines.append(item_text)

            # Add buttons for this generation
            lines.append("")  # Spacing

        lines.append(f"\n{T(lang, 'history_page', page=page + 1, total=total_pages)}")
        lines.append(T(lang, "history_month_limit"))

        text = "\n".join(lines)

        # Build keyboard with pagination and download buttons
        kb_rows = []

        # Add download/use buttons for each generation on this page
        for i, gen in enumerate(page_gens):
            row = [
                InlineKeyboardButton(
                    text=f"{T(lang, 'btn_download')} #{start_idx + i + 1}",
                    callback_data=f"hist:download:{gen.id}"
                ),
                InlineKeyboardButton(
                    text=f"{T(lang, 'btn_use_as_base')} #{start_idx + i + 1}",
                    callback_data=f"hist:use_base:{gen.id}"
                ),
            ]
            kb_rows.append(row)

        # Pagination buttons
        nav_row = []
        if page > 0:
            nav_row.append(
                InlineKeyboardButton(text=T(lang, "btn_prev_page"), callback_data=f"account:history:{page - 1}")
            )
        if page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(text=T(lang, "btn_next_page"), callback_data=f"account:history:{page + 1}")
            )
        if nav_row:
            kb_rows.append(nav_row)

        # Back button
        kb_rows.append([InlineKeyboardButton(text=T(lang, "btn_back"), callback_data="account:menu")])

        kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

        try:
            await q.message.edit_text(text, reply_markup=kb)
        except Exception:
            await q.message.answer(text, reply_markup=kb)
        await q.answer()

    @r.callback_query(F.data.startswith("hist:download:"))
    async def on_history_download(q: CallbackQuery):
        """Download images from a generation."""
        lang = await get_lang(q, db)
        gen_id = int(q.data.split(":")[-1])

        async with db.session() as s:
            # Get generation and its images
            gen = (await s.execute(select(Generation).where(Generation.id == gen_id))).scalar_one_or_none()

            if not gen or gen.user_id != q.from_user.id:
                await q.answer("Generation not found", show_alert=True)
                return

            # Get images
            images = (
                await s.execute(
                    select(GeneratedImage).where(GeneratedImage.generation_id == gen_id)
                )
            ).scalars().all()

        if not images:
            await q.answer("No images found", show_alert=True)
            return

        await q.answer("Downloading...")

        # Download and send images
        for i, img in enumerate(images):
            try:
                # Download from storage_url
                img_bytes = await asyncio.to_thread(seedream.download_file_bytes, img.storage_url)

                # Send as document
                from aiogram.types import BufferedInputFile
                await q.message.answer_document(
                    document=BufferedInputFile(img_bytes, filename=f"generation_{gen_id}_{i + 1}.png"),
                    caption=f"Generation #{gen_id} - Image {i + 1}/{len(images)}"
                )
            except Exception as e:
                logger.exception(f"Failed to download image {img.id}", exc_info=e)

    @r.callback_query(F.data.startswith("hist:use_base:"))
    async def on_history_use_as_base(q: CallbackQuery, state: FSMContext):
        """Use a historical generation as base for angles/poses stage."""
        lang = await get_lang(q, db)
        gen_id = int(q.data.split(":")[-1])

        async with db.session() as s:
            # Get generation and its images
            gen = (await s.execute(select(Generation).where(Generation.id == gen_id))).scalar_one_or_none()

            if not gen or gen.user_id != q.from_user.id:
                await q.answer("Generation not found", show_alert=True)
                return

            # Get images
            images = (
                await s.execute(
                    select(GeneratedImage).where(GeneratedImage.generation_id == gen_id)
                )
            ).scalars().all()

        if not images:
            await q.answer("No images found", show_alert=True)
            return

        # Download image bytes for state
        img_bytes = await asyncio.to_thread(seedream.download_file_bytes, images[0].storage_url)

        # Initialize angles/poses stage with this as base photo
        base_photo = {
            "url": images[0].storage_url,
            "bytes": img_bytes,
            "generation_id": gen_id,
            "background": (gen.params or {}).get("background", "white"),
            "hair": (gen.params or {}).get("hair", "any"),
            "style": (gen.params or {}).get("style", "casual"),
            "aspect": (gen.params or {}).get("aspect", "3_4"),
        }

        await state.update_data(
            base_photos=[base_photo],
            current_base_index=0,
        )
        await state.set_state(GenerationFlow.angles_poses_menu)

        await q.answer("Starting angles/poses stage...")
        await _show_angles_poses_menu(q.message, state, lang, db)
        await state.set_state(GenerationFlow.angles_poses_menu)

        await q.answer("Starting angles/poses stage...")
        await _show_angles_poses_menu(q.message, state, lang, db)

    # --- /buy (пополнение звездами) ---

    @r.message(Command("buy"))
    async def cmd_buy(m: Message, state: FSMContext):
        """Show payment method selection for top-up."""
        """Show payment method selection for top-up."""
        lang = await get_lang(m, db)
        await _show_payment_method_selection(m, lang)

    # --- Payment method selection callbacks ---

    @r.callback_query(F.data == "pay:stars")
    async def on_pay_stars(q: CallbackQuery, state: FSMContext):
        """Handle Telegram Stars payment selection."""
        lang = await get_lang(q, db)
        await pay.send_invoice(
            q.message,
            state=state,
            title=T(lang, "invoice_title"),
            desc=T(lang, "invoice_desc"),
            stars=1,
            payload=f"demo:{q.from_user.id}",
        )
        await q.answer()

    @r.callback_query(F.data == "pay:yookassa")
    async def on_pay_yookassa(q: CallbackQuery, state: FSMContext):
        """Handle YooKassa payment selection - create payment and show link."""
        lang = await get_lang(q, db)

        if not yookassa.enabled:
            await q.message.answer(T(lang, "yookassa_not_configured"))
            await q.answer()
            return

        await q.answer(T(lang, "yookassa_checking"))

        # Payment parameters
        # TODO: Add amount selection UI in future
        amount = "100.00"  # 100 rubles
        currency = "RUB"
        description = T(lang, "invoice_title")
        user_id = q.from_user.id

        # Create payment
        payment = yookassa.create_payment(
            amount=amount,
            currency=currency,
            description=f"{description} (User ID: {user_id})",
            user_id=user_id,
        )

        if not payment:
            await q.message.answer(T(lang, "yookassa_payment_error"))
            return

        # Store payment ID in FSM for later checking
        await state.update_data(yookassa_payment_id=payment["id"])

        logger.info(
            f"Created YooKassa payment {payment['id']} for user {user_id}, "
            f"amount {amount} {currency}"
        )

        # Create keyboard with payment link and check button
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_pay_now"), url=payment["confirmation_url"]
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_check_payment"),
                        callback_data=f"yookassa:check:{payment['id']}",
                    )
                ],
            ]
        )

        # Send payment details
        await q.message.answer(
            T(
                lang,
                "yookassa_payment_created",
                amount=payment["amount"],
                currency=payment["currency"],
                description=payment["description"],
                payment_id=payment["id"],
            ),
            reply_markup=keyboard,
        )

    @r.callback_query(F.data.startswith("yookassa:check:"))
    async def on_yookassa_check_payment(q: CallbackQuery, state: FSMContext):
        """Check YooKassa payment status."""
        lang = await get_lang(q, db)

        # Parse payment ID from callback data
        payment_id = q.data.split(":", 2)[2]
        user_id = q.from_user.id

        await q.answer(T(lang, "yookassa_checking"))

        # Get payment status
        payment = yookassa.get_payment_status(payment_id)

        if not payment:
            await q.message.answer(T(lang, "yookassa_check_error"))
            return

        logger.info(
            f"Checked payment {payment_id} for user {user_id}: "
            f"status={payment['status']}, paid={payment['paid']}"
        )

        status = payment["status"]
        paid = payment["paid"]

        # Handle different payment statuses
        if status == "succeeded" and paid:
            # Payment successful - update user balance
            from decimal import Decimal

            amount_rubles = Decimal(payment["amount"])
            credits_to_add = int(amount_rubles)  # 1 ruble = 1 credit

            async with db.session() as s:
                # Update user credits
                db_user = (
                    await s.execute(select(User).where(User.user_id == user_id))
                ).scalar_one_or_none()

                if db_user:
                    db_user.credits_balance = (db_user.credits_balance or 0) + credits_to_add

                # Record transaction
                await record_transaction(
                    s,
                    user_id=user_id,
                    kind=TransactionKind.purchase,
                    amount=amount_rubles,
                    currency=payment["currency"],
                    provider="yookassa",
                    status=TransactionStatus.succeeded,
                    title="YooKassa payment",
                    external_id=payment_id,
                    meta={"payment_status": status, "user_id": str(user_id)},
                )

                await s.commit()

            logger.info(
                f"Added {credits_to_add} credits to user {user_id} from YooKassa payment {payment_id}"
            )

            # Show success message
            await q.message.edit_text(
                T(
                    lang,
                    "yookassa_status_succeeded",
                    amount=payment["amount"],
                    currency=payment["currency"],
                    payment_id=payment_id,
                )
            )

        elif status == "canceled":
            # Payment canceled - show option to create new payment
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=T(lang, "btn_create_new_payment"),
                            callback_data="pay:yookassa",
                        )
                    ]
                ]
            )

            await q.message.edit_text(
                T(lang, "yookassa_status_canceled"), reply_markup=keyboard
            )

        else:
            # Payment still pending - show buttons again
            status_text = T(lang, "yookassa_status_pending")
            if status == "waiting_for_capture":
                status_text = T(lang, "yookassa_status_waiting")

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=T(lang, "btn_pay_now"),
                            url=payment.get("confirmation_url", yookassa.return_url),
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text=T(lang, "btn_check_payment"),
                            callback_data=f"yookassa:check:{payment_id}",
                        )
                    ],
                ]
            )

            await q.message.edit_text(
                f"{status_text}\n\n"
                f"💰 Сумма: {payment['amount']} {payment['currency']}\n"
                f"🆔 ID платежа: <code>{payment_id}</code>\n\n"
                f"Оплатите и нажмите кнопку проверки.",
                reply_markup=keyboard,
            )

        await q.answer()

    @r.callback_query(F.data == "pay:yookassa")
    async def on_pay_yookassa(q: CallbackQuery, state: FSMContext):
        """Handle YooKassa payment selection - create payment and show link."""
        lang = await get_lang(q, db)

        if not yookassa.enabled:
            await q.message.answer(T(lang, "yookassa_not_configured"))
            await q.answer()
            return

        await q.answer(T(lang, "yookassa_checking"))

        # Payment parameters
        # TODO: Add amount selection UI in future
        amount = "100.00"  # 100 rubles
        currency = "RUB"
        description = T(lang, "invoice_title")
        user_id = q.from_user.id

        # Create payment
        payment = yookassa.create_payment(
            amount=amount,
            currency=currency,
            description=f"{description} (User ID: {user_id})",
            user_id=user_id,
        )

        if not payment:
            await q.message.answer(T(lang, "yookassa_payment_error"))
            return

        # Store payment ID in FSM for later checking
        await state.update_data(yookassa_payment_id=payment["id"])

        logger.info(
            f"Created YooKassa payment {payment['id']} for user {user_id}, "
            f"amount {amount} {currency}"
        )

        # Create keyboard with payment link and check button
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_pay_now"), url=payment["confirmation_url"]
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_check_payment"),
                        callback_data=f"yookassa:check:{payment['id']}",
                    )
                ],
            ]
        )

        # Send payment details
        await q.message.answer(
            T(
                lang,
                "yookassa_payment_created",
                amount=payment["amount"],
                currency=payment["currency"],
                description=payment["description"],
                payment_id=payment["id"],
            ),
            reply_markup=keyboard,
        )

    @r.callback_query(F.data.startswith("yookassa:check:"))
    async def on_yookassa_check_payment(q: CallbackQuery, state: FSMContext):
        """Check YooKassa payment status."""
        lang = await get_lang(q, db)

        # Parse payment ID from callback data
        payment_id = q.data.split(":", 2)[2]
        user_id = q.from_user.id

        await q.answer(T(lang, "yookassa_checking"))

        # Get payment status
        payment = yookassa.get_payment_status(payment_id)

        if not payment:
            await q.message.answer(T(lang, "yookassa_check_error"))
            return

        logger.info(
            f"Checked payment {payment_id} for user {user_id}: "
            f"status={payment['status']}, paid={payment['paid']}"
        )

        status = payment["status"]
        paid = payment["paid"]

        # Handle different payment statuses
        if status == "succeeded" and paid:
            # Payment successful - update user balance
            from decimal import Decimal

            amount_rubles = Decimal(payment["amount"])
            credits_to_add = int(amount_rubles)  # 1 ruble = 1 credit

            async with db.session() as s:
                # Update user credits
                db_user = (
                    await s.execute(select(User).where(User.user_id == user_id))
                ).scalar_one_or_none()

                if db_user:
                    db_user.credits_balance = (db_user.credits_balance or 0) + credits_to_add

                # Record transaction
                await record_transaction(
                    s,
                    user_id=user_id,
                    kind=TransactionKind.purchase,
                    amount=amount_rubles,
                    currency=payment["currency"],
                    provider="yookassa",
                    status=TransactionStatus.succeeded,
                    title="YooKassa payment",
                    external_id=payment_id,
                    meta={"payment_status": status, "user_id": str(user_id)},
                )

                await s.commit()

            logger.info(
                f"Added {credits_to_add} credits to user {user_id} from YooKassa payment {payment_id}"
            )

            # Show success message
            await q.message.edit_text(
                T(
                    lang,
                    "yookassa_status_succeeded",
                    amount=payment["amount"],
                    currency=payment["currency"],
                    payment_id=payment_id,
                )
            )

        elif status == "canceled":
            # Payment canceled - show option to create new payment
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=T(lang, "btn_create_new_payment"),
                            callback_data="pay:yookassa",
                        )
                    ]
                ]
            )

            await q.message.edit_text(
                T(lang, "yookassa_status_canceled"), reply_markup=keyboard
            )

        else:
            # Payment still pending - show buttons again
            status_text = T(lang, "yookassa_status_pending")
            if status == "waiting_for_capture":
                status_text = T(lang, "yookassa_status_waiting")

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=T(lang, "btn_pay_now"),
                            url=payment.get("confirmation_url", yookassa.return_url),
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text=T(lang, "btn_check_payment"),
                            callback_data=f"yookassa:check:{payment_id}",
                        )
                    ],
                ]
            )

            await q.message.edit_text(
                f"{status_text}\n\n"
                f"💰 Сумма: {payment['amount']} {payment['currency']}\n"
                f"🆔 ID платежа: <code>{payment_id}</code>\n\n"
                f"Оплатите и нажмите кнопку проверки.",
                reply_markup=keyboard,
            )

    # --- /language (и /lang, /swith_lang для совместимости) ---

    @r.message(Command("language", "lang", "swith_lang"))
    async def cmd_switch_lang(m: Message):
        lang = await get_lang(m, db)
        await m.answer(T(lang, "choose_lang_title"), reply_markup=_build_lang_kb())


    @r.callback_query(F.data.startswith("gen:mode:"))
    async def on_gen_mode_select(query: CallbackQuery, state: FSMContext):
        """
        Пользователь выбрал сценарий:
        - gen:mode:all      -> единые настройки для всех вещей
        - gen:mode:per_item -> отдельные настройки для каждой вещи (пока заглушка)
        """
        from fsm import GenerationFlow

        lang = await get_lang(query, db)
        data = await state.get_data()

        mode = query.data.split(":", maxsplit=2)[-1]
        cloth_file_ids = list(data.get("cloth_file_ids") or [])
        num_items = len(cloth_file_ids) or 1

        if not cloth_file_ids:
            await query.answer(
                T(lang, "no_items_yet") or "Вы ещё не загрузили ни одной вещи.",
                show_alert=True,
            )
            return

        if mode == "per_item":
            await state.update_data(settings_mode="per_item", num_items=num_items)

            # удалим сообщение выбора режима, чтобы не дублировать UI
            try:
                await query.message.delete()
            except Exception:
                pass

            # стартуем настройку для первого элемента
            await state.update_data(per_item_index=0)

            # инициализируем контейнер под настройки на каждый элемент
            per_item_settings: list[dict[str, Any]] = [
                {
                    "backgrounds": [],
                    "gender": None,
                    "hair": None,
                    "hair_options": [],
                    "age": None,
                    "style": None,
                    "style_options": [],
                    "aspect": None,
                    "aspects": [],
                }
                for _ in range(num_items)
            ]
            await state.update_data(per_item_settings=per_item_settings)

            idx = 0
            file_id = cloth_file_ids[idx]
            photo_msg_id = None
            try:
                photo_msg = await query.message.answer_document(
                    file_id,
                    caption=T(lang, "per_item_photo_caption", idx=idx + 1, total=num_items)
                    if T(lang, "per_item_photo_caption", idx=1, total=1) != "per_item_photo_caption"
                    else f"Фото {idx+1}/{num_items}"
                )
                photo_msg_id = photo_msg.message_id
            except Exception:
                # если не удалось отправить как документ, игнорируем картинку и просто пойдём к настройкам
                pass

            intro_text = (
                T(lang, "per_item_intro", idx=idx + 1, total=num_items)
                if T(lang, "per_item_intro", idx=1, total=1) != "per_item_intro"
                else T(lang, "background_select_single")
            )
            kb = build_background_keyboard(lang, set())
            sent = await query.message.answer(intro_text, reply_markup=kb)

            await state.update_data(
                generate_prompt_msg_id=sent.message_id,
                generate_chat_id=sent.chat.id,
                per_item_photo_msg_id=photo_msg_id,
            )
            await state.set_state(GenerationFlow.choosing_background)
            await query.answer()
            return

        if mode == "all":
            await state.update_data(settings_mode="all", num_items=num_items)

            intro_text = T(lang, "settings_intro_single", count=num_items)
            base_text = T(lang, "background_select_single")
            full_text = f"{intro_text}\n\n{base_text}"

            # стартуем с пустого набора выбранных фонов
            selected_backgrounds: set[str] = set(data.get("backgrounds") or [])
            kb = build_background_keyboard(lang, selected_backgrounds)

            await query.answer()

            try:
                await query.message.edit_text(full_text, reply_markup=kb)
                msg_id = query.message.message_id
                chat_id = query.message.chat.id
            except Exception:
                sent = await query.message.answer(full_text, reply_markup=kb)
                msg_id = sent.message_id
                chat_id = sent.chat.id

            await state.update_data(
                generate_prompt_msg_id=msg_id,
                generate_chat_id=chat_id,
                backgrounds=list(selected_backgrounds),
            )
            await state.set_state(GenerationFlow.choosing_background)
            return

        await query.answer()


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

    # --- Назад из выбора режима к старту загрузки ---
    @r.callback_query(F.data == "gen:back_to_start")
    async def on_gen_back_to_start(q: CallbackQuery, state: FSMContext):
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
        try:
            await q.message.edit_text(T(lang, "generate_intro_short"), reply_markup=kb)
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
    async def on_document_for_generation(message: Message, state: FSMContext):
        """
        Пользователь присылает фото одежды (как документ) в сценарии генерации.
        Поддерживаем 1..N вещей:
        - накапливаем список cloth_file_ids
        - после каждой загрузки показываем/обновляем сообщение
          'Вы загрузили N вещей. Что вам удобнее?' с двумя сценариями.
        """
        from fsm import GenerationFlow

        # Реагируем только когда реально ждём документ в GenerationFlow
        current_state = await state.get_state()
        if current_state != GenerationFlow.waiting_document.state:
            return

        lang = await get_lang(message, db)

        doc = message.document
        if not doc or not doc.mime_type or not doc.mime_type.startswith("image/"):
            await message.answer(T(lang, "only_image_documents"))
            return

        data = await state.get_data()
        cloth_file_ids = list(data.get("cloth_file_ids") or [])
        cloth_file_ids.append(doc.file_id)
        num_items = len(cloth_file_ids)
        await state.update_data(cloth_file_ids=cloth_file_ids, num_items=num_items)

        # --- если загружена только 1 вещь: сразу идём в настройки (как gen:mode:all) ---
        if num_items == 1:
            # режим "единые настройки", сохраняем количество вещей
            await state.update_data(
                settings_mode="all",
                num_items=num_items,
            )

            # текст как при режиме all
            intro_text = T(lang, "settings_intro_single", count=num_items)
            base_text = T(lang, "background_select_single")
            full_text = f"{intro_text}\n\n{base_text}"

            # на первом шаге фон ещё не выбран
            selected_backgrounds: set[str] = set()
            kb = build_background_keyboard(lang, selected_backgrounds)

            sent = await message.answer(full_text, reply_markup=kb)

            await state.update_data(
                generate_prompt_msg_id=sent.message_id,
                generate_chat_id=sent.chat.id,
                backgrounds=list(selected_backgrounds),
            )
            await state.set_state(GenerationFlow.choosing_background)
            return

        # --- если вещей 2 и больше: показываем intro + выбор режима ---
        # при этом если уже показывали экран выбора фона (после первой вещи), удалим его,
        # чтобы не было двух активных сообщений
        prev_prompt_id = data.get("generate_prompt_msg_id")
        prev_prompt_chat = data.get("generate_chat_id")
        if prev_prompt_id and prev_prompt_chat:
            try:
                await message.bot.delete_message(chat_id=prev_prompt_chat, message_id=prev_prompt_id)
                await state.update_data(generate_prompt_msg_id=None, generate_chat_id=None)
            except Exception as e:
                logger.warning(f"Failed to delete background selection message: {e}")
        text = (
            T(lang, "multi_items_intro", count=num_items)
            or (
                f"Вы загрузили {num_items} вещей. Далее вы сможете выбрать фон, пол, возраст и цвет волос модели, "
                f"соотношение сторон и стиль фото на выходе.\n\nЧто вам удобнее?"
            )
        )

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_mode_all_items")
                        or "Задать единые настройки для всех вещей (быстрее)",
                        callback_data="gen:mode:all",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_mode_per_item")
                        or "Задать настройки для каждой вещи отдельно",
                        callback_data="gen:mode:per_item",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_back_to_start") or "Назад",
                        callback_data="gen:back_to_start",
                    )
                ],
            ]
        )

        items_msg_id = data.get("items_mode_msg_id")
        items_chat_id = data.get("items_mode_chat_id")

        if items_msg_id and items_chat_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=items_chat_id,
                    message_id=items_msg_id,
                    text=text,
                    reply_markup=kb,
                )
            except Exception:
                sent = await message.answer(text, reply_markup=kb)
                await state.update_data(
                    items_mode_msg_id=sent.message_id,
                    items_mode_chat_id=sent.chat.id,
                )
        else:
            sent = await message.answer(text, reply_markup=kb)
            await state.update_data(
                items_mode_msg_id=sent.message_id,
                items_mode_chat_id=sent.chat.id,
            )


    @r.callback_query(F.data == "gen:back_to_background")
    async def on_gen_back_to_background(q: CallbackQuery, state: FSMContext):
        """
        Возврат со шага выбора пола обратно к выбору фона.
        """
        from fsm import GenerationFlow

        lang = await get_lang(q, db)
        data = await state.get_data()

        settings_mode = data.get("settings_mode")
        if settings_mode == "per_item":
            idx = int(data.get("per_item_index") or 0)
            per_item_settings = list(data.get("per_item_settings") or [])
            current = per_item_settings[idx] if idx < len(per_item_settings) else {}
            selected = set(current.get("backgrounds") or [])
            intro_text = T(lang, "settings_intro_single", count=1)
        else:
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


    @r.callback_query(F.data == "gen:back_to_gender")
    async def on_gen_back_to_gender(q: CallbackQuery, state: FSMContext):
        """
        Возврат со шага выбора волос назад к выбору пола.
        """
        from fsm import GenerationFlow

        lang = await get_lang(q, db)
        data = await state.get_data()
        settings_mode = data.get("settings_mode")
        if settings_mode == "per_item":
            idx = int(data.get("per_item_index") or 0)
            per_item_settings = list(data.get("per_item_settings") or [])
            current = per_item_settings[idx] if idx < len(per_item_settings) else {}
            gender = current.get("gender") or "female"
        else:
            gender = data.get("gender") or "female"

        def btn_text(code: str, phrase_key: str) -> str:
            base = T(lang, phrase_key)
            return f"✅ {base}" if code == gender else base

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=btn_text("female", "btn_gender_female"),
                        callback_data="gen:gender:female",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=btn_text("male", "btn_gender_male"),
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
            await q.message.edit_text(
                T(lang, "gender_choose_title"),
                reply_markup=kb,
            )
        except Exception:
            await q.message.answer(
                T(lang, "gender_choose_title"),
                reply_markup=kb,
            )

        await state.set_state(GenerationFlow.choosing_gender)
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

        settings_mode = data.get("settings_mode")
        if settings_mode == "per_item":
            idx = int(data.get("per_item_index") or 0)
            per_item_settings = list(data.get("per_item_settings") or [])
            current = per_item_settings[idx] if idx < len(per_item_settings) else {}
            selected = set(current.get("backgrounds") or [])
        else:
            selected = set(data.get("backgrounds") or [])

        _, _, action = q.data.split(":", 2)

        # --- переключение конкретного цвета ---
        if action in BG_KEYS:
            if action in selected:
                selected.remove(action)
            else:
                selected.add(action)

            if settings_mode == "per_item":
                if idx < len(per_item_settings):
                    current = dict(current)
                    current["backgrounds"] = list(selected)
                    per_item_settings[idx] = current
                    await state.update_data(per_item_settings=per_item_settings)
            else:
                await state.update_data(backgrounds=list(selected))

            # Пересобираем текст
            intro_text = (
                T(lang, "settings_intro_single", count=1)
                if settings_mode == "per_item"
                else T(lang, "settings_intro_single", count=data.get("num_items") or 1)
            )
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
            if settings_mode == "per_item":
                if idx < len(per_item_settings):
                    current = dict(current)
                    current["backgrounds"] = list(selected)
                    current["background"] = main_bg
                    per_item_settings[idx] = current
                    await state.update_data(per_item_settings=per_item_settings)
            else:
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
        Выбор пола модели:
        - сохраняем gender
        - показываем шаг выбора цвета волос (мультивыбор)
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

        data = await state.get_data()
        settings_mode = data.get("settings_mode")
        if settings_mode == "per_item":
            idx = int(data.get("per_item_index") or 0)
            per_item_settings = list(data.get("per_item_settings") or [])
            if idx < len(per_item_settings):
                current = dict(per_item_settings[idx])
                current["gender"] = gender
                # default hair options for new step
                if not current.get("hair_options"):
                    current["hair_options"] = ["any"]
                per_item_settings[idx] = current
                await state.update_data(per_item_settings=per_item_settings)
        else:
            await state.update_data(gender=gender)

        data = await state.get_data()
        # по умолчанию считаем, что выбран вариант "Любой"
        if data.get("settings_mode") == "per_item":
            idx = int(data.get("per_item_index") or 0)
            pis = list(data.get("per_item_settings") or [])
            cur = pis[idx] if idx < len(pis) else {}
            selected_hairs = set(cur.get("hair_options") or {"any"})
        else:
            selected_hairs = set(data.get("hair_options") or {"any"})

        kb = build_hair_keyboard(lang, selected_hairs)

        try:
            await q.message.edit_text(
                T(lang, "settings_hair_title"),
                reply_markup=kb,
            )
        except Exception:
            await q.message.answer(
                T(lang, "settings_hair_title"),
                reply_markup=kb,
            )

        await state.set_state(GenerationFlow.choosing_hair)
        await q.answer()


    @r.callback_query(F.data == "gen:back_to_hair")
    async def on_gen_back_to_hair(q: CallbackQuery, state: FSMContext):
        """
        Возврат со шага возраста к выбору цвета волос (с сохранённым выбором).
        """
        from fsm import GenerationFlow

        lang = await get_lang(q, db)
        data = await state.get_data()
        if data.get("settings_mode") == "per_item":
            idx = int(data.get("per_item_index") or 0)
            pis = list(data.get("per_item_settings") or [])
            cur = pis[idx] if idx < len(pis) else {}
            selected = set(cur.get("hair_options") or {"any"})
        else:
            selected = set(data.get("hair_options") or {"any"})

        kb = build_hair_keyboard(lang, selected)

        # текст + список выбранных цветов
        if lang == "ru":
            labels = [HAIR_LABELS[h][0] for h in selected if h in HAIR_LABELS]
        else:
            labels = [HAIR_LABELS[h][1] for h in selected if h in HAIR_LABELS]

        base_text = T(lang, "settings_hair_title")
        if labels:
            selected_block = T(lang, "hair_selected_header") + "\n" + "\n".join(labels)
            full_text = base_text + "\n\n" + selected_block
        else:
            full_text = base_text

        try:
            await q.message.edit_text(full_text, reply_markup=kb)
        except Exception:
            await q.message.answer(full_text, reply_markup=kb)

        await state.set_state(GenerationFlow.choosing_hair)
        await q.answer()


    @r.callback_query(F.data.startswith("gen:hair:"))
    async def on_gen_choose_hair(q: CallbackQuery, state: FSMContext):
        """
        Мультивыбор цвета волос:
        - gen:hair:any|dark|light — тогаем выбранность
        - gen:hair:next          — фиксируем выбор и переходим к возрасту
        """
        from fsm import GenerationFlow

        current = await state.get_state()
        if current != GenerationFlow.choosing_hair.state:
            await q.answer()
            return

        lang = await get_lang(q, db)
        data = await state.get_data()
        action = q.data.split(":", 2)[-1]

        settings_mode = data.get("settings_mode")
        if settings_mode == "per_item":
            idx = int(data.get("per_item_index") or 0)
            pis = list(data.get("per_item_settings") or [])
            cur = pis[idx] if idx < len(pis) else {}
            selected = set(cur.get("hair_options") or set())
        else:
            selected = set(data.get("hair_options") or set())

        # --- тогаем чекбоксы ---
        if action in HAIR_KEYS:
            if action == "any":
                # "Любой" взаимоисключающий — сбрасываем остальные
                if "any" in selected:
                    selected.remove("any")
                else:
                    selected = {"any"}
            else:
                if action in selected:
                    selected.remove(action)
                else:
                    selected.add(action)
                # если выбрали конкретный цвет — убираем "any"
                if "any" in selected and len(selected) > 1:
                    selected.remove("any")

            if settings_mode == "per_item":
                if idx < len(pis):
                    cur = dict(cur)
                    cur["hair_options"] = list(selected)
                    pis[idx] = cur
                    await state.update_data(per_item_settings=pis)
            else:
                await state.update_data(hair_options=list(selected))

            # перерисовываем клавиатуру и текст
            if lang == "ru":
                labels = [HAIR_LABELS[h][0] for h in selected if h in HAIR_LABELS]
            else:
                labels = [HAIR_LABELS[h][1] for h in selected if h in HAIR_LABELS]

            base_text = T(lang, "settings_hair_title")
            if labels:
                selected_block = T(lang, "hair_selected_header") + "\n" + "\n".join(labels)
                full_text = base_text + "\n\n" + selected_block
            else:
                full_text = base_text

            kb = build_hair_keyboard(lang, selected)

            try:
                await q.message.edit_text(full_text, reply_markup=kb)
            except Exception:
                await q.message.edit_caption(full_text, reply_markup=kb)

            await q.answer()
            return

        # --- Next: валидируем и идём к возрасту ---
        if action == "next":
            if not selected:
                await q.answer(T(lang, "hair_need_one"), show_alert=True)
                return

            # effective список для логики:
            if selected == {"any"}:
                hair_main = "any"
                hair_options = ["any"]
            else:
                hair_options = [h for h in HAIR_KEYS if h in selected and h != "any"]
                hair_main = hair_options[0] if hair_options else "any"

            if settings_mode == "per_item":
                if idx < len(pis):
                    cur = dict(cur)
                    cur["hair"] = hair_main
                    cur["hair_options"] = hair_options
                    pis[idx] = cur
                    await state.update_data(per_item_settings=pis)
            else:
                await state.update_data(
                    hair=hair_main,
                    hair_options=hair_options,
                )

            # показываем выбор возраста
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
                            callback_data="gen:back_to_hair",
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
            return

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

        data0 = await state.get_data()
        if data0.get("settings_mode") == "per_item":
            idx = int(data0.get("per_item_index") or 0)
            pis = list(data0.get("per_item_settings") or [])
            if idx < len(pis):
                cur = dict(pis[idx])
                cur["age"] = age
                pis[idx] = cur
                await state.update_data(per_item_settings=pis)
        else:
            await state.update_data(age=age)

        data = await state.get_data()
        if data.get("settings_mode") == "per_item":
            idx = int(data.get("per_item_index") or 0)
            pis = list(data.get("per_item_settings") or [])
            cur = pis[idx] if idx < len(pis) else {}
            selected_styles = set(cur.get("style_options") or set())
        else:
            selected_styles = set(data.get("style_options") or set())

        kb = build_style_keyboard(lang, selected_styles)

        # базовый текст + выбранные стили (если есть)
        if lang == "ru":
            labels = [STYLE_LABELS[s][0] for s in selected_styles if s in STYLE_LABELS]
        else:
            labels = [STYLE_LABELS[s][1] for s in selected_styles if s in STYLE_LABELS]

        base_text = T(lang, "settings_style_title")
        if labels:
            selected_block = T(lang, "style_selected_header") + "\n" + "\n".join(labels)
            full_text = base_text + "\n\n" + selected_block
        else:
            full_text = base_text

        try:
            await q.message.edit_text(full_text, reply_markup=kb)
        except Exception:
            await q.message.answer(full_text, reply_markup=kb)

        await state.set_state(GenerationFlow.choosing_style)
        await q.answer()


    @r.callback_query(F.data == "gen:back_to_age")
    async def on_gen_back_to_age(q: CallbackQuery, state: FSMContext):
        """
        Возврат со шага стиля к выбору возраста.
        """
        from fsm import GenerationFlow

        lang = await get_lang(q, db)
        data = await state.get_data()
        if data.get("settings_mode") == "per_item":
            idx = int(data.get("per_item_index") or 0)
            pis = list(data.get("per_item_settings") or [])
            cur = pis[idx] if idx < len(pis) else {}
            age = cur.get("age") or "young"
        else:
            age = data.get("age") or "young"

        def btn_text(code: str, phrase_key: str) -> str:
            base = T(lang, phrase_key)
            return f"✅ {base}" if code == age else base

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=btn_text("young", "btn_age_young"),
                        callback_data="gen:age:young",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=btn_text("senior", "btn_age_senior"),
                        callback_data="gen:age:senior",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=btn_text("child", "btn_age_child"),
                        callback_data="gen:age:child",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=btn_text("teen", "btn_age_teen"),
                        callback_data="gen:age:teen",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=T(lang, "btn_back"),
                        callback_data="gen:back_to_hair",
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


    @r.callback_query(F.data == "gen:back_to_style")
    async def on_gen_back_to_style(q: CallbackQuery, state: FSMContext):
        """
        Возврат со шага аспектов к выбору стиля.
        """
        from fsm import GenerationFlow

        lang = await get_lang(q, db)
        data = await state.get_data()
        if data.get("settings_mode") == "per_item":
            idx = int(data.get("per_item_index") or 0)
            pis = list(data.get("per_item_settings") or [])
            cur = pis[idx] if idx < len(pis) else {}
            selected = set(cur.get("style_options") or set())
        else:
            selected = set(data.get("style_options") or set())

        kb = build_style_keyboard(lang, selected)

        if lang == "ru":
            labels = [STYLE_LABELS[s][0] for s in selected if s in STYLE_LABELS]
        else:
            labels = [STYLE_LABELS[s][1] for s in selected if s in STYLE_LABELS]

        base_text = T(lang, "settings_style_title")
        if labels:
            selected_block = T(lang, "style_selected_header") + "\n" + "\n".join(labels)
            full_text = base_text + "\n\n" + selected_block
        else:
            full_text = base_text

        try:
            await q.message.edit_text(full_text, reply_markup=kb)
        except Exception:
            await q.message.answer(full_text, reply_markup=kb)

        await state.set_state(GenerationFlow.choosing_style)
        await q.answer()


    @r.callback_query(F.data.startswith("gen:style:"))
    async def on_gen_choose_style(q: CallbackQuery, state: FSMContext):
        """
        Мультивыбор стиля:
        - gen:style:strict|luxury|casual|sport — тогаем
        - gen:style:next                      — фиксируем и переходим к аспектам
        """
        from fsm import GenerationFlow

        current = await state.get_state()
        if current != GenerationFlow.choosing_style.state:
            await q.answer()
            return

        lang = await get_lang(q, db)
        action = q.data.split(":", 2)[-1]
        data = await state.get_data()
        settings_mode = data.get("settings_mode")
        if settings_mode == "per_item":
            idx = int(data.get("per_item_index") or 0)
            pis = list(data.get("per_item_settings") or [])
            cur = pis[idx] if idx < len(pis) else {}
            selected = set(cur.get("style_options") or set())
        else:
            selected = set(data.get("style_options") or set())

        if action in STYLE_KEYS:
            if action in selected:
                selected.remove(action)
            else:
                selected.add(action)

            if settings_mode == "per_item":
                if idx < len(pis):
                    cur = dict(cur)
                    cur["style_options"] = list(selected)
                    pis[idx] = cur
                    await state.update_data(per_item_settings=pis)
            else:
                await state.update_data(style_options=list(selected))

            if lang == "ru":
                labels = [STYLE_LABELS[s][0] for s in selected if s in STYLE_LABELS]
            else:
                labels = [STYLE_LABELS[s][1] for s in selected if s in STYLE_LABELS]

            base_text = T(lang, "settings_style_title")
            if labels:
                selected_block = T(lang, "style_selected_header") + "\n" + "\n".join(labels)
                full_text = base_text + "\n\n" + selected_block
            else:
                full_text = base_text

            kb = build_style_keyboard(lang, selected)

            try:
                await q.message.edit_text(full_text, reply_markup=kb)
            except Exception:
                await q.message.edit_caption(full_text, reply_markup=kb)

            await q.answer()
            return

        if action == "next":
            if not selected:
                await q.answer(T(lang, "style_need_one"), show_alert=True)
                return

            style_options = [s for s in STYLE_KEYS if s in selected]
            style_main = style_options[0]

            if settings_mode == "per_item":
                if idx < len(pis):
                    cur = dict(cur)
                    cur["style"] = style_main
                    cur["style_options"] = style_options
                    pis[idx] = cur
                    await state.update_data(per_item_settings=pis)
            else:
                await state.update_data(
                    style=style_main,
                    style_options=style_options,
                )

            # переходим к выбору аспектов
            if settings_mode == "per_item":
                idx = int(data.get("per_item_index") or 0)
                pis = list(data.get("per_item_settings") or [])
                cur = pis[idx] if idx < len(pis) else {}
                aspects_selected = set(cur.get("aspects") or set())
            else:
                aspects_selected = set(data.get("aspects") or set())
            kb = build_aspect_keyboard(lang, aspects_selected)

            if lang == "ru":
                labels = [ASPECT_LABELS[a][0] for a in aspects_selected if a in ASPECT_LABELS]
            else:
                labels = [ASPECT_LABELS[a][1] for a in aspects_selected if a in ASPECT_LABELS]

            base_text = T(lang, "settings_aspect_title")
            if labels:
                selected_block = T(lang, "aspect_selected_header") + "\n" + "\n".join(labels)
                full_text = base_text + "\n\n" + selected_block
            else:
                full_text = base_text

            try:
                await q.message.edit_text(full_text, reply_markup=kb)
            except Exception:
                await q.message.answer(full_text, reply_markup=kb)

            from fsm import GenerationFlow
            await state.set_state(GenerationFlow.choosing_aspect)
            await q.answer()
            return

        await q.answer()


    @r.callback_query(F.data.startswith("gen:aspect:"))
    async def on_gen_choose_aspect(q: CallbackQuery, state: FSMContext):
        from fsm import GenerationFlow

        current = await state.get_state()
        if current != GenerationFlow.choosing_aspect.state:
            await q.answer()
            return

        lang = await get_lang(q, db)
        action = q.data.split(":", 2)[-1]
        data = await state.get_data()

        settings_mode = data.get("settings_mode")
        if settings_mode == "per_item":
            idx = int(data.get("per_item_index") or 0)
            pis = list(data.get("per_item_settings") or [])
            cur = pis[idx] if idx < len(pis) else {}
            selected = set(cur.get("aspects") or set())
        else:
            selected = set(data.get("aspects") or set())

        # --- тогаем чекбоксы ---
        if action in ASPECT_KEYS:
            if action in selected:
                selected.remove(action)
            else:
                selected.add(action)

            if settings_mode == "per_item":
                if idx < len(pis):
                    cur = dict(cur)
                    cur["aspects"] = list(selected)
                    pis[idx] = cur
                    await state.update_data(per_item_settings=pis)
            else:
                await state.update_data(aspects=list(selected))

            if lang == "ru":
                labels = [ASPECT_LABELS[a][0] for a in selected if a in ASPECT_LABELS]
            else:
                labels = [ASPECT_LABELS[a][1] for a in selected if a in ASPECT_LABELS]

            base_text = T(lang, "settings_aspect_title")
            if labels:
                selected_block = T(lang, "aspect_selected_header") + "\n" + "\n".join(labels)
                full_text = base_text + "\n\n" + selected_block
            else:
                full_text = base_text

            kb = build_aspect_keyboard(lang, selected)

            try:
                await q.message.edit_text(full_text, reply_markup=kb)
            except Exception:
                await q.message.edit_caption(full_text, reply_markup=kb)

            await q.answer()
            return

        # --- Next: считаем комбинаторику и рисуем summary ---
        if action == "next":
            if not selected:
                await q.answer(T(lang, "aspect_need_one"), show_alert=True)
                return
            aspects = [a for a in ASPECT_KEYS if a in selected]
            aspect_main = aspects[0]

            if settings_mode == "per_item":
                # сохраняем для текущего элемента
                if idx < len(pis):
                    cur = dict(cur)
                    cur["aspect"] = aspect_main
                    cur["aspects"] = aspects
                    pis[idx] = cur
                    await state.update_data(per_item_settings=pis)

                num_items = int(data.get("num_items") or 1)
                # переходим к следующему элементу или рисуем сводку
                next_idx = idx + 1
                if next_idx < num_items:
                    await state.update_data(per_item_index=next_idx)

                    # Delete previous item's photo and configuration messages
                    prev_photo_msg_id = data.get("per_item_photo_msg_id")
                    prev_config_msg_id = data.get("generate_prompt_msg_id")
                    prev_chat_id = data.get("generate_chat_id")

                    if prev_photo_msg_id and prev_chat_id:
                        try:
                            await q.bot.delete_message(chat_id=prev_chat_id, message_id=prev_photo_msg_id)
                        except Exception as e:
                            logger.warning(f"Failed to delete previous item photo: {e}")

                    if prev_config_msg_id and prev_chat_id:
                        try:
                            await q.bot.delete_message(chat_id=prev_chat_id, message_id=prev_config_msg_id)
                        except Exception as e:
                            logger.warning(f"Failed to delete previous config message: {e}")

                    # Show next item photo
                    cloth_file_ids = list(data.get("cloth_file_ids") or [])
                    photo_msg_id = None
                    if next_idx < len(cloth_file_ids):
                        file_id = cloth_file_ids[next_idx]
                        try:
                            photo_msg = await q.message.answer_document(
                                file_id,
                                caption=(
                                    T(lang, "per_item_photo_caption", idx=next_idx + 1, total=num_items)
                                    if T(lang, "per_item_photo_caption", idx=1, total=1) != "per_item_photo_caption"
                                    else f"Фото {next_idx+1}/{num_items}"
                                ),
                            )
                            photo_msg_id = photo_msg.message_id
                        except Exception as e:
                            logger.warning(f"Failed to send next item photo: {e}")

                    # Show configuration screen for next item
                    intro_text = (
                        T(lang, "per_item_intro", idx=next_idx + 1, total=num_items)
                        if T(lang, "per_item_intro", idx=1, total=1) != "per_item_intro"
                        else T(lang, "background_select_single")
                    )
                    kb = build_background_keyboard(lang, set())
                    sent = await q.message.answer(intro_text, reply_markup=kb)

                    await state.update_data(
                        generate_prompt_msg_id=sent.message_id,
                        generate_chat_id=sent.chat.id,
                        per_item_photo_msg_id=photo_msg_id,
                    )

                    await state.set_state(GenerationFlow.choosing_background)
                    await q.answer()
                    return

                # все элементы настроены — считаем суммарное число фото
                def _count_photos_for_item(item: dict[str, Any]) -> int:
                    bgs = item.get("backgrounds") or [item.get("background") or "white"]
                    bgs = list(dict.fromkeys(bgs))
                    hair_opts = item.get("hair_options") or [item.get("hair") or "any"]
                    if hair_opts == ["any"]:
                        hcount = 1
                    else:
                        hcount = len([h for h in HAIR_KEYS if h in hair_opts and h != "any"]) or 1
                    s_opts = list(dict.fromkeys(item.get("style_options") or [item.get("style") or "casual"]))
                    a_opts = list(dict.fromkeys(item.get("aspects") or [item.get("aspect") or "3_4"]))
                    return max(len(bgs), 1) * hcount * max(len(s_opts), 1) * max(len(a_opts), 1)

                total_photos = sum(_count_photos_for_item(it) for it in pis)

                async with db.session() as s:
                    prof = await get_profile(s, tg_user_id=q.from_user.id)
                    balance = prof.credits_balance

                # короткая сводка: всего вещей и фото
                base_text = T(
                    lang,
                    "confirm_generation_title_total_only",
                    items=len(pis),
                    photos=total_photos,
                    balance=balance,
                )
                if base_text == "confirm_generation_title_total_only":
                    base_text = f"Всего вещей: {len(pis)}\nБудет сгенерировано фото: {total_photos}\nБаланс: {balance}"

                extra_text = (
                    "\n\n" + T(lang, "confirm_generation_ok")
                    if balance >= total_photos
                    else "\n\n" + T(lang, "confirm_generation_not_enough")
                )

                kb_buttons = [
                    [InlineKeyboardButton(text=T(lang, "btn_confirm_next"), callback_data="gen:confirm:next")]
                ]
                if balance < total_photos:
                    kb_buttons.append([
                        InlineKeyboardButton(text=T(lang, "btn_confirm_topup"), callback_data="gen:confirm:topup")
                    ])
                kb_buttons.append([
                    InlineKeyboardButton(text=T(lang, "btn_back"), callback_data="gen:aspect_back")
                ])

                kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)

                try:
                    await q.message.edit_text(base_text + extra_text, reply_markup=kb)
                except Exception:
                    await q.message.answer(base_text + extra_text, reply_markup=kb)

                await state.set_state(GenerationFlow.confirming)
                await q.answer()
                return

            # режим all — как раньше: рисуем итоговую сводку
            aspects = [a for a in ASPECT_KEYS if a in selected]
            aspect_main = aspects[0]
            await state.update_data(aspect=aspect_main, aspects=aspects)

            data = await state.get_data()
            num_items = int(data.get("num_items") or 1)

            # фоны
            bg_key = data.get("background") or "white"
            backgrounds = data.get("backgrounds") or [bg_key]
            backgrounds = list(dict.fromkeys(backgrounds))

            # волосы
            hair_main = data.get("hair") or "any"
            hair_options = data.get("hair_options") or [hair_main]
            if not hair_options:
                hair_options = ["any"]

            # стиль
            style_main = data.get("style") or "casual"
            style_options = data.get("style_options") or [style_main]
            style_options = list(dict.fromkeys(style_options))

            # читаемые подписи
            if lang == "ru":
                bg_labels = [BG_LABELS[k][0] for k in backgrounds if k in BG_LABELS]
                hair_labels = [HAIR_LABELS[h][0] for h in hair_options if h in HAIR_LABELS]
                style_labels = [STYLE_LABELS[s][0] for s in style_options if s in STYLE_LABELS]
                aspect_labels = [ASPECT_LABELS[a][0] for a in aspects if a in ASPECT_LABELS]
            else:
                bg_labels = [BG_LABELS[k][1] for k in backgrounds if k in BG_LABELS]
                hair_labels = [HAIR_LABELS[h][1] for h in hair_options if h in HAIR_LABELS]
                style_labels = [STYLE_LABELS[s][1] for s in style_options if s in STYLE_LABELS]
                aspect_labels = [ASPECT_LABELS[a][1] for a in aspects if a in ASPECT_LABELS]

            background_str = ", ".join(bg_labels) if bg_labels else "-"
            hair_str = ", ".join(hair_labels) if hair_labels else "-"
            style_str = ", ".join(style_labels) if style_labels else "-"
            aspect_str = ", ".join(aspect_labels) if aspect_labels else "-"

            # комбинаторика
            bg_count = max(len(backgrounds), 1)
            hair_count = 1 if hair_options == ["any"] else len(hair_options)
            style_count = max(len(style_options), 1)
            aspect_count = max(len(aspects), 1)

            photos = num_items * bg_count * hair_count * style_count * aspect_count

            # профиль и баланс
            async with db.session() as s:
                prof = await get_profile(s, tg_user_id=q.from_user.id)
                balance = prof.credits_balance

            base_text = T(
                lang,
                "confirm_generation_title",
                items=num_items,
                background=background_str,
                gender=(
                    GENDER_LABELS[data.get("gender") or "female"][0 if lang == "ru" else 1]
                ),
                hair=hair_str,
                age=(
                    AGE_LABELS[data.get("age") or "young"][0 if lang == "ru" else 1]
                ),
                style=style_str,
                aspect=aspect_str,
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
            return

        await q.answer()


    @r.callback_query(F.data == "gen:aspect_back")
    async def on_gen_aspect_back(q: CallbackQuery, state: FSMContext):
        """
        Из экрана подтверждения (summary) назад к выбору соотношения сторон.
        """
        from fsm import GenerationFlow

        lang = await get_lang(q, db)
        data = await state.get_data()
        selected = set(data.get("aspects") or set())

        kb = build_aspect_keyboard(lang, selected)

        if lang == "ru":
            labels = [ASPECT_LABELS[a][0] for a in selected if a in ASPECT_LABELS]
        else:
            labels = [ASPECT_LABELS[a][1] for a in selected if a in ASPECT_LABELS]

        base_text = T(lang, "settings_aspect_title")
        if labels:
            selected_block = T(lang, "aspect_selected_header") + "\n" + "\n".join(labels)
            full_text = base_text + "\n\n" + selected_block
        else:
            full_text = base_text

        try:
            await q.message.edit_text(full_text, reply_markup=kb)
        except Exception:
            await q.message.answer(full_text, reply_markup=kb)

        await state.set_state(GenerationFlow.choosing_aspect)
        await q.answer()


    @r.callback_query(F.data.startswith("gen:confirm:"))
    async def on_gen_confirm(q: CallbackQuery, state: FSMContext, bot: Bot):
        """
        Подтверждение генерации:
        - action=next: создаём Generation, списываем кредиты, шлём задачи во все комбинации
          (фон × волосы × стиль × соотношение сторон), с ретраями до 3 попыток на комбинацию.
        - action=topup: просто напоминаем про пополнение
        Ошибка по одной комбинации НЕ ломает остальные.
        """
        from fsm import GenerationFlow
        from db import GeneratedImage, ImageRole  # локальный импорт

        current = await state.get_state()
        if current != GenerationFlow.confirming.state:
            await q.answer()
            return

        lang = await get_lang(q, db)
        action = q.data.split(":", 2)[-1]

        await q.answer()  # чтобы не словить timeout

        if action == "topup":
            await q.message.answer(T(lang, "no_credits"))
            return

        if action != "next":
            return

        data = await state.get_data()

        cloth_file_ids = list(data.get("cloth_file_ids") or [])
        if not cloth_file_ids:
            await q.message.answer(T(lang, "generation_failed"))
            await state.clear()
            return

        upload_type = data.get("upload_type") or "flat"
        settings_mode = data.get("settings_mode")

        # загрузим все изображения и получим их URLs
        cloth_urls: list[str] = []
        for tg_file_id in cloth_file_ids:
            file_buf = BytesIO()
            try:
                await bot.download(file=tg_file_id, destination=file_buf)
                file_buf.seek(0)
                cloth_bytes = file_buf.read()
            except Exception as e:
                await state.clear()
                err_text = T(lang, "generation_failed")
                try:
                    await q.message.edit_text(err_text)
                except Exception:
                    await q.message.answer(err_text)
                logger.exception("Telegram file download failed", exc_info=e)
                return

            try:
                cloth_url = await asyncio.to_thread(
                    seedream.upload_image_bytes,
                    cloth_bytes,
                    f"cloth_{tg_file_id}.jpg",
                )
                cloth_urls.append(cloth_url)
            except Exception as e:
                await state.clear()
                err_text = T(lang, "generation_failed")
                try:
                    await q.message.edit_text(err_text)
                except Exception:
                    await q.message.answer(err_text)
                logger.exception("Seedream upload_image_bytes failed", exc_info=e)
                return

        # подготовим параметры и план
        if settings_mode == "per_item":
            pis = list(data.get("per_item_settings") or [])
            num_items = len(pis)

            def _item_counts(item: dict[str, Any]) -> tuple[list[str], list[str|None], list[str], list[str]]:
                bgs = list(dict.fromkeys(item.get("backgrounds") or [item.get("background") or "white"]))
                hair_opts = item.get("hair_options") or [item.get("hair") or "any"]
                if hair_opts == ["any"]:
                    hair_combo = [None]
                else:
                    hair_combo = [h for h in HAIR_KEYS if h in hair_opts and h != "any"]
                styles = list(dict.fromkeys(item.get("style_options") or [item.get("style") or "casual"]))
                aspects = list(dict.fromkeys(item.get("aspects") or [item.get("aspect") or "3_4"]))
                return bgs, hair_combo, styles, aspects

            # Calculate total number of combinations
            total_combinations = 0
            for it in pis:
                bgs, hair_combo, styles, aspects = _item_counts(it)
                total_combinations += max(len(bgs), 1) * (1 if hair_combo == [None] else len(hair_combo)) * max(len(styles), 1) * max(len(aspects), 1)

            # Check if user has enough credits for ALL combinations (1 credit per combination)
            price_per_generation = GEN_SCENARIO_PRICES.get("initial_generation", 1)
            total_cost = total_combinations * price_per_generation

            async with db.session() as s:
                user_db = (
                    await s.execute(select(User).where(User.user_id == q.from_user.id))
                ).scalar_one_or_none()

                if user_db is None:
                    await state.clear()
                    try:
                        await q.message.edit_text(T(lang, "no_credits"))
                    except Exception:
                        await q.message.answer(T(lang, "no_credits"))
                    return

                current_balance = int(user_db.credits_balance or 0)
                if current_balance < total_cost:
                    await state.clear()
                    try:
                        await q.message.edit_text(T(lang, "no_credits"))
                    except Exception:
                        await q.message.answer(T(lang, "no_credits"))
                    return

            try:
                await q.message.edit_text(T(lang, "processing_generation"))
            except Exception:
                await q.message.answer(T(lang, "processing_generation"))

            task_meta_list: list[dict[str, Any]] = []
            failed_on_create = 0
            for idx, it in enumerate(pis):
                bgs, hair_combo, styles, aspects = _item_counts(it)
                gender_i = it.get("gender") or "female"
                age_i = it.get("age") or "young"
                age_snip_i = AGE_SNIPPETS.get(age_i)
                cloth_url = cloth_urls[idx] if idx < len(cloth_urls) else cloth_urls[0]
                for bg in bgs:
                    bg_snip = BG_SNIPPETS[bg]
                    for hair_code in hair_combo:
                        hair_snip = HAIR_SNIPPETS[hair_code] if hair_code else None
                        for style_code in styles:
                            style_snip = STYLE_SNIPPETS[style_code]
                            for asp in aspects:
                                image_size, image_resolution = ASPECT_PARAMS[asp]
                                prompt_for_task = seedream.build_ecom_prompt(
                                    gender=gender_i,
                                    hair_color=hair_snip,
                                    age=age_snip_i,
                                    style_snippet=style_snip,
                                    background_snippet=bg_snip,
                                )

                                # Create generation record and deduct credit for this specific combination
                                async with db.session() as s:
                                    gen_obj, user, price = await ensure_credits_and_create_generation(
                                        s,
                                        tg_user_id=q.from_user.id,
                                        prompt=prompt_for_task,
                                        scenario_key="initial_generation",
                                        total_images_planned=1,
                                        params={
                                            "scenario": "per_item_generation",
                                            "upload_type": upload_type,
                                            "item_index": idx,
                                            "background": bg,
                                            "hair": hair_code or "any",
                                            "style": style_code,
                                            "aspect": asp,
                                        },
                                        source_image_urls=[cloth_url],
                                    )

                                    if gen_obj is None:
                                        failed_on_create += 1
                                        logger.warning(f"Failed to create generation for combo: bg={bg}, hair={hair_code}, style={style_code}, aspect={asp}")
                                        continue

                                    # Flush to ensure the ID is assigned
                                    await s.flush()
                                    generation_id = gen_obj.id

                                try:
                                    task_id = await asyncio.to_thread(
                                        seedream.create_task,
                                        prompt_for_task,
                                        image_size=image_size,
                                        image_resolution=image_resolution,
                                        max_images=1,
                                        image_urls=[cloth_url],
                                    )
                                    task_meta_list.append(
                                        {
                                            "task_id": task_id,
                                            "generation_id": generation_id,
                                            "background": bg,
                                            "hair": hair_code or "any",
                                            "style": style_code,
                                            "aspect": asp,
                                            "prompt": prompt_for_task,
                                            "image_size": image_size,
                                            "image_resolution": image_resolution,
                                            "max_images": 1,
                                            "cloth_url": cloth_url,
                                        }
                                    )

                                    # Update generation status to running
                                    async with db.session() as s:
                                        gen_db = (
                                            await s.execute(select(Generation).where(Generation.id == generation_id))
                                        ).scalar_one_or_none()
                                        if gen_db:
                                            gen_db.external_id = task_id
                                            gen_db.status = GenerationStatus.running

                                except Exception as e:
                                    # Task creation failed - mark generation as failed and refund credit
                                    async with db.session() as s:
                                        gen_db = (
                                            await s.execute(select(Generation).where(Generation.id == generation_id))
                                        ).scalar_one_or_none()
                                        user_db = (
                                            await s.execute(select(User).where(User.user_id == q.from_user.id))
                                        ).scalar_one_or_none()

                                        if gen_db:
                                            gen_db.status = GenerationStatus.failed
                                            gen_db.error_message = f"Task creation failed: {str(e)}"
                                            gen_db.finished_at = datetime.now(timezone.utc)
                                        if user_db and gen_db:
                                            user_db.credits_balance = (user_db.credits_balance or 0) + gen_db.credits_spent

                                    failed_on_create += 1
                                    logger.exception("Seedream create_task failed (per-item)", extra={"item": idx, "error": repr(e)})

        else:
            # режим all — генерация по всем вещам с едиными настройками
            num_items = int(data.get("num_items") or 1)

            backgrounds = list(dict.fromkeys(data.get("backgrounds") or [data.get("background") or "white"]))
            hair_main = data.get("hair") or "any"
            hair_options = data.get("hair_options") or [hair_main]
            hair_combo_codes: list[str | None] = [None] if hair_options == ["any"] else [h for h in HAIR_KEYS if h in hair_options and h != "any"]
            age = data.get("age") or "young"
            style_main = data.get("style") or "casual"
            style_options = list(dict.fromkeys(data.get("style_options") or [style_main]))
            aspect_main = data.get("aspect") or "3_4"
            aspect_options = list(dict.fromkeys(data.get("aspects") or [aspect_main]))
            gender = data.get("gender") or "female"

            age_snippet = AGE_SNIPPETS.get(age)

            bg_count = max(len(backgrounds), 1)
            hair_count = 1 if hair_combo_codes == [None] else len(hair_combo_codes)
            style_count = max(len(style_options), 1)
            aspect_count = max(len(aspect_options), 1)
            total_combinations = len(cloth_urls) * bg_count * hair_count * style_count * aspect_count

            # Check if user has enough credits for ALL combinations (1 credit per combination)
            price_per_generation = GEN_SCENARIO_PRICES.get("initial_generation", 1)
            total_cost = total_combinations * price_per_generation

            async with db.session() as s:
                user_db = (
                    await s.execute(select(User).where(User.user_id == q.from_user.id))
                ).scalar_one_or_none()

                if user_db is None:
                    await state.clear()
                    try:
                        await q.message.edit_text(T(lang, "no_credits"))
                    except Exception:
                        await q.message.answer(T(lang, "no_credits"))
                    return

                current_balance = int(user_db.credits_balance or 0)
                if current_balance < total_cost:
                    await state.clear()
                    try:
                        await q.message.edit_text(T(lang, "no_credits"))
                    except Exception:
                        await q.message.answer(T(lang, "no_credits"))
                    return

            try:
                await q.message.edit_text(T(lang, "processing_generation"))
            except Exception:
                await q.message.answer(T(lang, "processing_generation"))

            task_meta_list: list[dict[str, Any]] = []
            failed_on_create = 0
            for cloth_url in cloth_urls:
                for bg in backgrounds:
                    bg_snip = BG_SNIPPETS[bg]
                    for hair_code in hair_combo_codes:
                        hair_snip = HAIR_SNIPPETS[hair_code] if hair_code else None
                        for style_code in style_options:
                            style_snip = STYLE_SNIPPETS[style_code]
                            for asp in aspect_options:
                                image_size, image_resolution = ASPECT_PARAMS[asp]
                                prompt_for_task = seedream.build_ecom_prompt(
                                    gender=gender,
                                    hair_color=hair_snip,
                                    age=age_snippet,
                                    style_snippet=style_snip,
                                    background_snippet=bg_snip,
                                )

                                # Create generation record and deduct credit for this specific combination
                                async with db.session() as s:
                                    gen_obj, user, price = await ensure_credits_and_create_generation(
                                        s,
                                        tg_user_id=q.from_user.id,
                                        prompt=prompt_for_task,
                                        scenario_key="initial_generation",
                                        total_images_planned=1,
                                        params={
                                            "scenario": "initial_generation",
                                            "upload_type": upload_type,
                                            "gender": gender,
                                            "age": age,
                                            "background": bg,
                                            "hair": hair_code or "any",
                                            "style": style_code,
                                            "aspect": asp,
                                        },
                                        source_image_urls=[cloth_url],
                                    )

                                    if gen_obj is None:
                                        failed_on_create += 1
                                        logger.warning(f"Failed to create generation for combo: bg={bg}, hair={hair_code}, style={style_code}, aspect={asp}")
                                        continue

                                    # Flush to ensure the ID is assigned
                                    await s.flush()
                                    generation_id = gen_obj.id

                                try:
                                    task_id = await asyncio.to_thread(
                                        seedream.create_task,
                                        prompt_for_task,
                                        image_size=image_size,
                                        image_resolution=image_resolution,
                                        max_images=1,
                                        image_urls=[cloth_url],
                                    )
                                    task_meta_list.append(
                                        {
                                            "task_id": task_id,
                                            "generation_id": generation_id,
                                            "background": bg,
                                            "hair": hair_code or "any",
                                            "style": style_code,
                                            "aspect": asp,
                                            "prompt": prompt_for_task,
                                            "image_size": image_size,
                                            "image_resolution": image_resolution,
                                            "max_images": 1,
                                            "cloth_url": cloth_url,
                                        }
                                    )

                                    # Update generation status to running
                                    async with db.session() as s:
                                        gen_db = (
                                            await s.execute(select(Generation).where(Generation.id == generation_id))
                                        ).scalar_one_or_none()
                                        if gen_db:
                                            gen_db.external_id = task_id
                                            gen_db.status = GenerationStatus.running

                                except Exception as e:
                                    # Task creation failed - mark generation as failed and refund credit
                                    async with db.session() as s:
                                        gen_db = (
                                            await s.execute(select(Generation).where(Generation.id == generation_id))
                                        ).scalar_one_or_none()
                                        user_db = (
                                            await s.execute(select(User).where(User.user_id == q.from_user.id))
                                        ).scalar_one_or_none()

                                        if gen_db:
                                            gen_db.status = GenerationStatus.failed
                                            gen_db.error_message = f"Task creation failed: {str(e)}"
                                            gen_db.finished_at = datetime.now(timezone.utc)
                                        if user_db and gen_db:
                                            user_db.credits_balance = (user_db.credits_balance or 0) + gen_db.credits_spent

                                    failed_on_create += 1
                                    logger.exception("Seedream create_task failed (all-mode)", extra={"error": repr(e)})

        # Check if any tasks were created
        if not task_meta_list:
            await state.clear()
            err_text = T(lang, "generation_failed")
            try:
                await q.message.edit_text(err_text)
            except Exception:
                await q.message.answer(err_text)
            return

        # Notify user about task submission
        first_task_id = task_meta_list[0]["task_id"]
        notify_text = T(lang, "task_queued", task_id=first_task_id)
        try:
            await q.message.edit_text(notify_text)
        except Exception:
            await q.message.answer(notify_text)

        # --- Process results for all tasks and update individual generation status ---
        image_records: list[dict[str, Any]] = []
        failed_combos = 0

        for meta in task_meta_list:
            generation_id = meta["generation_id"]
            combo_success = False
            last_error: Exception | None = None

            for attempt in range(1, 4):  # до 3 попыток на комбинацию
                task_id = meta["task_id"]
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
                        raise RuntimeError(
                            f"No resultJson in task_info={task_info!r}"
                        )

                    result_obj = json.loads(result_json_str)
                    result_urls = result_obj.get("resultUrls") or []
                    if not result_urls:
                        raise RuntimeError(
                            f"No resultUrls in resultJson={result_obj!r}"
                        )

                    # Success - download images and update generation status
                    for url in result_urls:
                        download_url = await asyncio.to_thread(
                            seedream.get_download_url, url
                        )
                        img_bytes = await asyncio.to_thread(
                            seedream.download_file_bytes, download_url
                        )
                        image_records.append(
                            {
                                "url": url,
                                "bytes": img_bytes,
                                "generation_id": generation_id,
                                "background": meta["background"],
                                "hair": meta["hair"],
                                "style": meta["style"],
                                "aspect": meta["aspect"],
                            }
                        )

                    # Update generation status to succeeded
                    async with db.session() as s:
                        gen_db = (
                            await s.execute(select(Generation).where(Generation.id == generation_id))
                        ).scalar_one_or_none()
                        if gen_db:
                            gen_db.status = GenerationStatus.succeeded
                            gen_db.images_generated = len(result_urls)
                            gen_db.finished_at = datetime.now(timezone.utc)

                    combo_success = True
                    break  # выходим из цикла попыток для этой комбинации

                except Exception as e:
                    last_error = e
                    logger.warning(
                        "Seedream combo failed (wait/result) "
                        "— for task {task_id}",
                        extra={
                            "task_id": task_id,
                            "meta": meta,
                            "error": repr(e),
                        },
                    )

                    if attempt >= 3:
                        # исчерпали попытки, выходим, комбо считаем проваленным
                        break

                    # пробуем создать новый task для этой же комбинации
                    try:
                        new_task_id = await asyncio.to_thread(
                            seedream.create_task,
                            meta["prompt"],
                            image_size=meta["image_size"],
                            image_resolution=meta["image_resolution"],
                            max_images=meta.get("max_images", 1),
                            image_urls=[meta["cloth_url"]],
                        )
                        meta["task_id"] = new_task_id

                        # Update generation with new external_id
                        async with db.session() as s:
                            gen_db = (
                                await s.execute(select(Generation).where(Generation.id == generation_id))
                            ).scalar_one_or_none()
                            if gen_db:
                                gen_db.external_id = new_task_id

                    except Exception as e2:
                        last_error = e2
                        logger.warning(
                            "Seedream re-create_task failed for combo retry",
                            extra={
                                "meta": meta,
                                "attempt": attempt,
                                "error": repr(e2),
                            },
                        )
                        # пойдём на следующую попытку, если она ещё есть
                        continue

            if not combo_success:
                # All retries failed - mark generation as failed and refund credit
                failed_combos += 1
                logger.error(
                    "All retries failed for combo",
                    extra={"meta": meta, "last_error": repr(last_error)},
                )

                async with db.session() as s:
                    gen_db = (
                        await s.execute(select(Generation).where(Generation.id == generation_id))
                    ).scalar_one_or_none()
                    user_db = (
                        await s.execute(select(User).where(User.user_id == q.from_user.id))
                    ).scalar_one_or_none()

                    if gen_db:
                        gen_db.status = GenerationStatus.failed
                        gen_db.error_message = f"All retries failed: {str(last_error)}"
                        gen_db.finished_at = datetime.now(timezone.utc)
                    if user_db and gen_db:
                        user_db.credits_balance = (user_db.credits_balance or 0) + gen_db.credits_spent

        # Check if we got any images
        if not image_records:
            await state.clear()
            err_text = T(lang, "generation_failed")
            try:
                await q.message.edit_text(err_text)
            except Exception:
                await q.message.answer(err_text)
            return

        # Save generated images to database
        async with db.session() as s:
            for rec in image_records:
                img = GeneratedImage(
                    generation_id=rec["generation_id"],
                    user_id=q.from_user.id,
                    role=ImageRole.base,
                    storage_url=rec["url"],
                    telegram_file_id=None,
                    width=None,
                    height=None,
                    meta={
                        "scenario": data.get("settings_mode") == "per_item" and "per_item_generation" or "initial_generation",
                        "upload_type": upload_type,
                        "background": rec["background"],
                        "hair": rec["hair"],
                        "style": rec["style"],
                        "aspect": rec["aspect"],
                    },
                )
                s.add(img)

        # --- 14. Initialize photo review workflow ---
        # Store all photos in state for interactive review
        await state.update_data(
            review_photos=image_records,  # All generated photos
            current_photo_index=0,  # Index of currently displayed photo
            approved_photos=[],  # List of approved photo indices
            rejected_photos=[],  # List of rejected photo indices
        )

        # Set state to reviewing_photos
        await state.set_state(GenerationFlow.reviewing_photos)

        # Show first photo with approval buttons
        await _show_photo_for_review(q.message, state, lang, db)


    # --- Photo review helper function ---
    async def _show_photo_for_review(message: Message, state: FSMContext, lang: str, db: Database):
        """Show current photo with approval buttons."""
        from aiogram.types import BufferedInputFile

        data = await state.get_data()
        photos = data.get("review_photos", [])
        current_idx = data.get("current_photo_index", 0)
        approved = data.get("approved_photos", [])

        if current_idx >= len(photos):
            # No more photos to review
            if approved:
                # Has approved photos - move to new angles/poses stage
                await message.answer(T(lang, "all_photos_reviewed", approved=len(approved)))
                await message.answer(T(lang, "moving_to_angles"))

                # Get approved photos data
                approved_photos_data = [photos[idx] for idx in approved]

                # Initialize angles/poses stage
                await state.update_data(
                    base_photos=approved_photos_data,
                    current_base_index=0,
                )
                await state.set_state(GenerationFlow.angles_poses_menu)

                # Show first base photo menu
                await _show_angles_poses_menu(message, state, lang, db)
            else:
                # No approved photos - show redo dialog
                await message.answer(T(lang, "no_more_photos"))
            return

        # Get current photo
        photo = photos[current_idx]
        total = len(photos)
        caption = f"{T(lang, 'photo_review_title', current=current_idx + 1, total=total)}\n\n{T(lang, 'photo_review_question')}"

        # Send as uncompressed document for original quality
        doc_msg = await message.answer_document(
            document=BufferedInputFile(
                photo["bytes"],
                filename=f"generation_{current_idx + 1}.png"
            ),
            caption=caption,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=T(lang, "btn_approve"),
                            callback_data=f"review:approve:{current_idx}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text=T(lang, "btn_redo"),
                            callback_data=f"review:redo:{current_idx}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text=T(lang, "btn_reject"),
                            callback_data=f"review:reject:{current_idx}"
                        )
                    ],
                ]
            )
        )

        # Store document file_id for later use
        if doc_msg.document:
            async with db.session() as s:
                img_db = (
                    await s.execute(
                        select(GeneratedImage).where(
                            GeneratedImage.user_id == message.from_user.id,
                            GeneratedImage.storage_url == photo["url"],
                        )
                    )
                ).scalar_one_or_none()
                if img_db:
                    img_db.telegram_file_id = doc_msg.document.file_id


    # --- Photo review handlers ---
    @r.callback_query(F.data.startswith("review:approve:"))
    async def on_photo_approve(q: CallbackQuery, state: FSMContext):
        """Handle photo approval."""
        lang = await get_lang(q, db)
        current = await state.get_state()

        if current != GenerationFlow.reviewing_photos.state:
            await q.answer()
            return

        # Get photo index from callback data
        photo_idx = int(q.data.split(":")[-1])

        # Update state
        data = await state.get_data()
        approved = data.get("approved_photos", [])
        if photo_idx not in approved:
            approved.append(photo_idx)

        await state.update_data(
            approved_photos=approved,
            current_photo_index=photo_idx + 1
        )

        await q.answer(T(lang, "photo_approved"))

        # Delete the current message
        try:
            await q.message.delete()
        except Exception:
            pass

        # Show next photo
        await _show_photo_for_review(q.message, state, lang, db)


    @r.callback_query(F.data.startswith("review:reject:"))
    async def on_photo_reject(q: CallbackQuery, state: FSMContext):
        """Handle photo rejection."""
        lang = await get_lang(q, db)
        current = await state.get_state()

        if current != GenerationFlow.reviewing_photos.state:
            await q.answer()
            return

        photo_idx = int(q.data.split(":")[-1])

        # Update state
        data = await state.get_data()
        rejected = data.get("rejected_photos", [])
        if photo_idx not in rejected:
            rejected.append(photo_idx)

        photos = data.get("review_photos", [])
        approved = data.get("approved_photos", [])

        await state.update_data(
            rejected_photos=rejected,
            current_photo_index=photo_idx + 1
        )

        await q.answer(T(lang, "photo_rejected"))

        # Delete the current message
        try:
            await q.message.delete()
        except Exception:
            pass

        # Check if this was the only photo and there are no approved ones
        if len(photos) == 1 and not approved:
            # Show redo dialog for single photo
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=T(lang, "btn_redo_same"),
                            callback_data="review:redo_single:same"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text=T(lang, "btn_redo_new"),
                            callback_data="review:redo_single:new"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text=T(lang, "btn_return_menu"),
                            callback_data="gen:back_to_start"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text=T(lang, "btn_topup_balance"),
                            callback_data="gen:topup"
                        )
                    ],
                ]
            )
            await q.message.answer(T(lang, "redo_question"), reply_markup=kb)
        else:
            # Show next photo
            await _show_photo_for_review(q.message, state, lang, db)


    @r.callback_query(F.data.startswith("review:redo:"))
    async def on_photo_redo(q: CallbackQuery, state: FSMContext):
        """Handle photo redo request."""
        lang = await get_lang(q, db)
        current = await state.get_state()

        if current != GenerationFlow.reviewing_photos.state:
            await q.answer()
            return

        photo_idx = int(q.data.split(":")[-1])

        # Check if user has enough credits (1 credit per generation)
        async with db.session() as s:
            user_db = (
                await s.execute(select(User).where(User.user_id == q.from_user.id))
            ).scalar_one_or_none()

            if not user_db or (user_db.credits_balance or 0) < 1:
                # Insufficient balance
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=T(lang, "btn_topup_balance"),
                                callback_data="gen:topup"
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text=T(lang, "btn_back"),
                                callback_data="review:back_to_review"
                            )
                        ],
                    ]
                )
                await q.answer(T(lang, "insufficient_balance"), show_alert=True)
                await q.message.answer(T(lang, "insufficient_balance"), reply_markup=kb)
                return

        # Implement regeneration with same settings
        data = await state.get_data()
        photos = data.get("review_photos", [])

        if photo_idx >= len(photos):
            await q.answer("Photo not found", show_alert=True)
            return

        photo = photos[photo_idx]
        generation_id = photo.get("generation_id")

        if not generation_id:
            await q.answer("Cannot retrieve generation parameters", show_alert=True)
            return

        # Retrieve original generation parameters from database
        async with db.session() as s:
            original_gen = (
                await s.execute(select(Generation).where(Generation.id == generation_id))
            ).scalar_one_or_none()

            if not original_gen:
                await q.answer("Original generation not found", show_alert=True)
                return

            # Create new generation with same parameters
            gen_obj, user, price = await ensure_credits_and_create_generation(
                s,
                tg_user_id=q.from_user.id,
                prompt=original_gen.prompt,
                scenario_key="initial_generation",
                total_images_planned=1,
                params=original_gen.params,
                source_image_urls=original_gen.source_image_urls,
            )

            if gen_obj is None:
                await q.answer(T(lang, "insufficient_balance"), show_alert=True)
                return

            await s.flush()
            new_generation_id = gen_obj.id

        # Show processing message
        try:
            await q.message.edit_caption(caption=T(lang, "processing_generation"))
        except Exception:
            await q.message.answer(T(lang, "processing_generation"))

        await q.answer()

        # Submit task to Seedream
        try:
            async with db.session() as s:
                original_gen_refresh = (
                    await s.execute(select(Generation).where(Generation.id == generation_id))
                ).scalar_one_or_none()

                params = original_gen_refresh.params or {}
                aspect = params.get("aspect", "3_4")
                image_size, image_resolution = ASPECT_PARAMS.get(aspect, ("768x1024", "768x1024"))

                task_id = await asyncio.to_thread(
                    seedream.create_task,
                    prompt=original_gen_refresh.prompt,
                    image_urls=original_gen_refresh.source_image_urls if original_gen_refresh.source_image_urls else None,
                    image_size=image_size,
                    image_resolution=image_resolution,
                )

                # Update generation status
                gen_db = (
                    await s.execute(select(Generation).where(Generation.id == new_generation_id))
                ).scalar_one_or_none()
                if gen_db:
                    gen_db.external_id = task_id
                    gen_db.status = GenerationStatus.running

        except Exception as e:
            # Refund credits on task creation failure
            async with db.session() as s:
                gen_db = (
                    await s.execute(select(Generation).where(Generation.id == new_generation_id))
                ).scalar_one_or_none()
                user_db = (
                    await s.execute(select(User).where(User.user_id == q.from_user.id))
                ).scalar_one_or_none()

                if gen_db:
                    gen_db.status = GenerationStatus.failed
                    gen_db.error_message = f"Task creation failed: {str(e)}"
                    gen_db.finished_at = datetime.now(timezone.utc)
                if user_db and gen_db:
                    user_db.credits_balance = (user_db.credits_balance or 0) + gen_db.credits_spent

            logger.exception("Seedream create_task failed (redo)", exc_info=e)
            await q.message.answer(T(lang, "generation_failed"))

            # Move to next photo (fault tolerance)
            data = await state.get_data()
            current_idx = data.get("current_photo_index", 0)
            await state.update_data(current_photo_index=current_idx + 1)
            await _show_photo_for_review(q.message, state, lang, db)
            return

        # Poll for results with detailed logging
        logger.info(f"Starting to poll for redo task_id={task_id} generation_id={new_generation_id}")
        max_retries = 3
        retry_count = 0
        last_error = None
        result_urls = None

        while retry_count < max_retries:
            try:
                logger.info(f"Redo poll attempt {retry_count + 1}/{max_retries} for task_id={task_id}")

                task_info = await asyncio.to_thread(
                    seedream.wait_for_result,
                    task_id,
                    poll_interval=5.0,
                    timeout=180.0,
                )

                logger.info(f"Redo task_id={task_id} completed, parsing results")
                logger.debug(f"Full task_info response: {task_info}")

                data_info = task_info.get("data", {})
                result_json_str = data_info.get("resultJson")

                if not result_json_str:
                    raise RuntimeError(f"No resultJson in task_info for task_id={task_id}")

                logger.debug(f"resultJson string: {result_json_str}")
                result_obj = json.loads(result_json_str)
                result_urls = result_obj.get("resultUrls") or []

                if not result_urls:
                    raise RuntimeError(f"No resultUrls in resultJson for task_id={task_id}")

                logger.info(f"Successfully got {len(result_urls)} result URLs for task_id={task_id}: {result_urls}")
                break

            except Exception as e:
                last_error = e
                retry_count += 1
                logger.warning(
                    f"Redo polling attempt {retry_count} failed for task_id={task_id}",
                    extra={"error": repr(e), "task_id": task_id, "generation_id": new_generation_id}
                )
                if retry_count < max_retries:
                    sleep_time = 2 ** retry_count
                    logger.info(f"Sleeping {sleep_time}s before retry")
                    await asyncio.sleep(sleep_time)

        if not result_urls:
            # All retries failed - refund credits
            async with db.session() as s:
                gen_db = (
                    await s.execute(select(Generation).where(Generation.id == new_generation_id))
                ).scalar_one_or_none()
                user_db = (
                    await s.execute(select(User).where(User.user_id == q.from_user.id))
                ).scalar_one_or_none()

                if gen_db:
                    gen_db.status = GenerationStatus.failed
                    gen_db.error_message = f"All retries failed: {str(last_error)}"
                    gen_db.finished_at = datetime.now(timezone.utc)
                if user_db and gen_db:
                    user_db.credits_balance = (user_db.credits_balance or 0) + gen_db.credits_spent

            logger.error(
                f"Redo generation failed after all retries for task_id={task_id}",
                extra={
                    "error": repr(last_error),
                    "task_id": task_id,
                    "generation_id": new_generation_id,
                    "photo_idx": photo_idx
                },
                exc_info=last_error
            )
            await q.message.answer(T(lang, "generation_failed"))

            # Move to next photo (fault tolerance)
            data = await state.get_data()
            current_idx = data.get("current_photo_index", 0)
            await state.update_data(current_photo_index=current_idx + 1)
            await _show_photo_for_review(q.message, state, lang, db)
            return

        # Download new image
        try:
            logger.info(f"Downloading redo result from {result_urls[0]}")
            download_url = await asyncio.to_thread(seedream.get_download_url, result_urls[0])
            logger.info(f"Got download URL: {download_url}")

            img_bytes = await asyncio.to_thread(seedream.download_file_bytes, download_url)
            logger.info(f"Successfully downloaded {len(img_bytes)} bytes for redo")
        except Exception as e:
            logger.exception(
                f"Failed to download regenerated image for task_id={task_id}",
                extra={
                    "task_id": task_id,
                    "generation_id": new_generation_id,
                    "result_urls": result_urls,
                    "error": repr(e)
                },
                exc_info=e
            )
            await q.message.answer(T(lang, "generation_failed"))

            # Move to next photo (fault tolerance)
            data = await state.get_data()
            current_idx = data.get("current_photo_index", 0)
            await state.update_data(current_photo_index=current_idx + 1)
            await _show_photo_for_review(q.message, state, lang, db)
            return

        # Update generation status to succeeded
        async with db.session() as s:
            gen_db = (
                await s.execute(select(Generation).where(Generation.id == new_generation_id))
            ).scalar_one_or_none()
            if gen_db:
                gen_db.status = GenerationStatus.succeeded
                gen_db.images_generated = 1
                gen_db.finished_at = datetime.now(timezone.utc)

            # Save to database
            img = GeneratedImage(
                generation_id=new_generation_id,
                user_id=q.from_user.id,
                role=ImageRole.base,
                storage_url=result_urls[0],
                telegram_file_id=None,
            )
            s.add(img)

        # Replace photo in review list
        photos[photo_idx] = {
            "url": result_urls[0],
            "bytes": img_bytes,
            "generation_id": new_generation_id,
            "background": photo.get("background"),
            "hair": photo.get("hair"),
            "style": photo.get("style"),
            "aspect": photo.get("aspect"),
        }
        await state.update_data(review_photos=photos)

        # Show the new photo
        await _show_photo_for_review(q.message, state, lang, db)


    @r.callback_query(F.data == "review:back_to_review")
    async def on_back_to_review(q: CallbackQuery, state: FSMContext):
        """Return to photo review."""
        lang = await get_lang(q, db)
        try:
            await q.message.delete()
        except Exception:
            pass
        await _show_photo_for_review(q.message, state, lang, db)
        await q.answer()


    @r.callback_query(F.data.startswith("review:redo_single:"))
    async def on_single_photo_redo(q: CallbackQuery, state: FSMContext):
        """Handle redo for single photo batch."""
        lang = await get_lang(q, db)
        action = q.data.split(":")[-1]

        if action == "new":
            # Return to design stage with option to start fresh generation
            data = await state.get_data()
            photos = data.get("review_photos", [])

            if photos:
                # Store the rejected photo info for potential replacement later
                photo = photos[0]
                generation_id = photo.get("generation_id")

                # Get original cloth file IDs if available
                cloth_file_ids = data.get("cloth_file_ids", [])

                # Clear state and restart generation flow
                await state.clear()

                # If we have the original cloth files, restore them
                if cloth_file_ids:
                    await state.update_data(cloth_file_ids=cloth_file_ids, num_items=len(cloth_file_ids))

                # Show upload type selection to restart the flow
                await q.message.answer(
                    T(lang, "upload_type_prompt"),
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text=T(lang, "btn_flat"),
                                    callback_data="gen:type:flat"
                                )
                            ],
                            [
                                InlineKeyboardButton(
                                    text=T(lang, "btn_model"),
                                    callback_data="gen:type:model"
                                )
                            ],
                            [
                                InlineKeyboardButton(
                                    text=T(lang, "btn_back"),
                                    callback_data="gen:back_to_start"
                                )
                            ],
                        ]
                    )
                )
                await state.set_state(GenerationFlow.selecting_upload_type)
                await q.answer()
            else:
                await state.clear()
                await q.message.answer(T(lang, "start_generation"))
                await q.answer()

        elif action == "same":
            # Redo with same settings
            data = await state.get_data()
            photos = data.get("review_photos", [])

            if not photos:
                await q.answer("No photo to regenerate", show_alert=True)
                return

            photo = photos[0]
            generation_id = photo.get("generation_id")

            if not generation_id:
                await q.answer("Cannot retrieve generation parameters", show_alert=True)
                return

            # Check balance first
            async with db.session() as s:
                user_db = (
                    await s.execute(select(User).where(User.user_id == q.from_user.id))
                ).scalar_one_or_none()

                if not user_db or (user_db.credits_balance or 0) < 1:
                    kb = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text=T(lang, "btn_topup_balance"),
                                    callback_data="gen:topup"
                                )
                            ],
                            [
                                InlineKeyboardButton(
                                    text=T(lang, "btn_return_menu"),
                                    callback_data="gen:back_to_start"
                                )
                            ],
                        ]
                    )
                    await q.answer(T(lang, "insufficient_balance"), show_alert=True)
                    await q.message.answer(T(lang, "insufficient_balance"), reply_markup=kb)
                    return

                # Retrieve original generation
                original_gen = (
                    await s.execute(select(Generation).where(Generation.id == generation_id))
                ).scalar_one_or_none()

                if not original_gen:
                    await q.answer("Original generation not found", show_alert=True)
                    return

                # Create new generation with same parameters
                gen_obj, user, price = await ensure_credits_and_create_generation(
                    s,
                    tg_user_id=q.from_user.id,
                    prompt=original_gen.prompt,
                    scenario_key="initial_generation",
                    total_images_planned=1,
                    params=original_gen.params,
                    source_image_urls=original_gen.source_image_urls,
                )

                if gen_obj is None:
                    await q.answer(T(lang, "insufficient_balance"), show_alert=True)
                    return

                await s.flush()
                new_generation_id = gen_obj.id

            # Show processing message
            await q.message.answer(T(lang, "processing_generation"))
            await q.answer()

            # Submit task to Seedream
            try:
                async with db.session() as s:
                    original_gen_refresh = (
                        await s.execute(select(Generation).where(Generation.id == generation_id))
                    ).scalar_one_or_none()

                    params = original_gen_refresh.params or {}
                    aspect = params.get("aspect", "3_4")
                    image_size, image_resolution = ASPECT_PARAMS.get(aspect, ("768x1024", "768x1024"))

                    task_id = await asyncio.to_thread(
                        seedream.create_task,
                        prompt=original_gen_refresh.prompt,
                        image_urls=original_gen_refresh.source_image_urls if original_gen_refresh.source_image_urls else None,
                        image_size=image_size,
                        image_resolution=image_resolution,
                    )

                    # Update generation status
                    gen_db = (
                        await s.execute(select(Generation).where(Generation.id == new_generation_id))
                    ).scalar_one_or_none()
                    if gen_db:
                        gen_db.external_id = task_id
                        gen_db.status = GenerationStatus.running

            except Exception as e:
                # Refund credits on task creation failure
                async with db.session() as s:
                    gen_db = (
                        await s.execute(select(Generation).where(Generation.id == new_generation_id))
                    ).scalar_one_or_none()
                    user_db = (
                        await s.execute(select(User).where(User.user_id == q.from_user.id))
                    ).scalar_one_or_none()

                    if gen_db:
                        gen_db.status = GenerationStatus.failed
                        gen_db.error_message = f"Task creation failed: {str(e)}"
                        gen_db.finished_at = datetime.now(timezone.utc)
                    if user_db and gen_db:
                        user_db.credits_balance = (user_db.credits_balance or 0) + gen_db.credits_spent

                logger.exception("Seedream create_task failed (redo single)", exc_info=e)
                await q.message.answer(T(lang, "generation_failed"))
                return

            # Poll for results with detailed logging
            logger.info(f"Starting to poll for redo single task_id={task_id} generation_id={new_generation_id}")
            max_retries = 3
            retry_count = 0
            last_error = None
            result_urls = None

            while retry_count < max_retries:
                try:
                    logger.info(f"Redo single poll attempt {retry_count + 1}/{max_retries} for task_id={task_id}")

                    task_info = await asyncio.to_thread(
                        seedream.wait_for_result,
                        task_id,
                        poll_interval=5.0,
                        timeout=180.0,
                    )

                    logger.info(f"Redo single task_id={task_id} completed, parsing results")
                    logger.debug(f"Full task_info response: {task_info}")

                    data_info = task_info.get("data", {})
                    result_json_str = data_info.get("resultJson")

                    if not result_json_str:
                        raise RuntimeError(f"No resultJson in task_info for task_id={task_id}")

                    logger.debug(f"resultJson string: {result_json_str}")
                    result_obj = json.loads(result_json_str)
                    result_urls = result_obj.get("resultUrls") or []

                    if not result_urls:
                        raise RuntimeError(f"No resultUrls in resultJson for task_id={task_id}")

                    logger.info(f"Successfully got {len(result_urls)} result URLs for task_id={task_id}: {result_urls}")
                    break

                except Exception as e:
                    last_error = e
                    retry_count += 1
                    logger.warning(
                        f"Redo single polling attempt {retry_count} failed for task_id={task_id}",
                        extra={"error": repr(e), "task_id": task_id, "generation_id": new_generation_id}
                    )
                    if retry_count < max_retries:
                        sleep_time = 2 ** retry_count
                        logger.info(f"Sleeping {sleep_time}s before retry")
                        await asyncio.sleep(sleep_time)

            if not result_urls:
                # All retries failed - refund credits
                async with db.session() as s:
                    gen_db = (
                        await s.execute(select(Generation).where(Generation.id == new_generation_id))
                    ).scalar_one_or_none()
                    user_db = (
                        await s.execute(select(User).where(User.user_id == q.from_user.id))
                    ).scalar_one_or_none()

                    if gen_db:
                        gen_db.status = GenerationStatus.failed
                        gen_db.error_message = f"All retries failed: {str(last_error)}"
                        gen_db.finished_at = datetime.now(timezone.utc)
                    if user_db and gen_db:
                        user_db.credits_balance = (user_db.credits_balance or 0) + gen_db.credits_spent

                logger.error(
                    f"Redo single generation failed after all retries for task_id={task_id}",
                    extra={
                        "error": repr(last_error),
                        "task_id": task_id,
                        "generation_id": new_generation_id
                    },
                    exc_info=last_error
                )
                await q.message.answer(T(lang, "generation_failed"))
                return

            # Download new image
            try:
                logger.info(f"Downloading redo single result from {result_urls[0]}")
                download_url = await asyncio.to_thread(seedream.get_download_url, result_urls[0])
                logger.info(f"Got download URL: {download_url}")

                img_bytes = await asyncio.to_thread(seedream.download_file_bytes, download_url)
                logger.info(f"Successfully downloaded {len(img_bytes)} bytes for redo single")
            except Exception as e:
                logger.exception(
                    f"Failed to download regenerated image (redo single) for task_id={task_id}",
                    extra={
                        "task_id": task_id,
                        "generation_id": new_generation_id,
                        "result_urls": result_urls,
                        "error": repr(e)
                    },
                    exc_info=e
                )
                await q.message.answer(T(lang, "generation_failed"))
                return

            # Update generation status
            async with db.session() as s:
                gen_db = (
                    await s.execute(select(Generation).where(Generation.id == new_generation_id))
                ).scalar_one_or_none()
                if gen_db:
                    gen_db.status = GenerationStatus.succeeded
                    gen_db.images_generated = 1
                    gen_db.finished_at = datetime.now(timezone.utc)

                # Save to database
                img = GeneratedImage(
                    generation_id=new_generation_id,
                    user_id=q.from_user.id,
                    role=ImageRole.base,
                    storage_url=result_urls[0],
                    telegram_file_id=None,
                )
                s.add(img)

            # Replace photo in review list
            photos[0] = {
                "url": result_urls[0],
                "bytes": img_bytes,
                "generation_id": new_generation_id,
                "background": photo.get("background"),
                "hair": photo.get("hair"),
                "style": photo.get("style"),
                "aspect": photo.get("aspect"),
            }
            await state.update_data(review_photos=photos)

            # Return to review state and show the new photo
            await state.set_state(GenerationFlow.reviewing_photos)
            await _show_photo_for_review(q.message, state, lang, db)


    @r.callback_query(F.data == "gen:topup")
    async def on_topup_from_review(q: CallbackQuery):
        """Handle topup request from review."""
        lang = await get_lang(q, db)
        await q.message.answer(T(lang, "no_credits"))
        await q.answer()


    # ==================================================================
    # ANGLES AND POSES STAGE (Stage 6)
    # ==================================================================

    async def _show_angles_poses_menu(message: Message, state: FSMContext, lang: str, db: Database):
        """Show the angles/poses menu for the current base photo."""
        from aiogram.types import BufferedInputFile

        data = await state.get_data()
        base_photos = data.get("base_photos", [])
        current_idx = data.get("current_base_index", 0)

        if current_idx >= len(base_photos):
            # All base photos processed
            await message.answer(T(lang, "all_base_photos_complete"))
            await state.clear()
            return

        base_photo = base_photos[current_idx]

        # Show base photo with menu
        caption = f"{T(lang, 'angles_intro')}\n\n{T(lang, 'angles_base_photo')}"

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=T(lang, "btn_change_pose"), callback_data="angles:pose:1")],
                [InlineKeyboardButton(text=T(lang, "btn_change_pose_5x"), callback_data="angles:pose:5")],
                [InlineKeyboardButton(text=T(lang, "btn_change_angle"), callback_data="angles:angle:1")],
                [InlineKeyboardButton(text=T(lang, "btn_change_angle_5x"), callback_data="angles:angle:5")],
                [InlineKeyboardButton(text=T(lang, "btn_add_rear_view"), callback_data="angles:rear")],
                [InlineKeyboardButton(text=T(lang, "btn_full_body"), callback_data="angles:full_body")],
                [InlineKeyboardButton(text=T(lang, "btn_upper_body"), callback_data="angles:upper_body")],
                [InlineKeyboardButton(text=T(lang, "btn_lower_body"), callback_data="angles:lower_body")],
                [InlineKeyboardButton(text=T(lang, "btn_finish_photo"), callback_data="angles:finish")],
            ]
        )

        await message.answer_document(
            document=BufferedInputFile(
                base_photo["bytes"],
                filename=f"base_photo_{current_idx + 1}.png"
            ),
            caption=caption,
            reply_markup=kb
        )


    @r.callback_query(F.data.startswith("angles:pose:") | F.data.startswith("angles:angle:"))
    async def on_angles_pose_angle(q: CallbackQuery, state: FSMContext):
        """Handle pose/angle change requests."""
        lang = await get_lang(q, db)
        await q.answer()

        # Parse action: angles:pose:1 or angles:angle:5
        parts = q.data.split(":")
        action_type = parts[1]  # "pose" or "angle"
        count = int(parts[2])   # 1 or 5

        data = await state.get_data()
        base_photos = data.get("base_photos", [])
        current_idx = data.get("current_base_index", 0)

        if current_idx >= len(base_photos):
            await q.message.answer(T(lang, "all_base_photos_complete"))
            return

        base_photo = base_photos[current_idx]
        generation_id = base_photo.get("generation_id")

        # Build prompt based on action type
        if action_type == "pose":
            prompt = "Change pose"
        else:  # angle
            prompt = "Change angle"

        # Get aspect ratio from base photo params
        aspect = base_photo.get("aspect", "3_4")
        image_size, image_resolution = ASPECT_PARAMS.get(aspect, ("768x1024", "768x1024"))

        # Check credits
        async with db.session() as s:
            user_db = (
                await s.execute(select(User).where(User.user_id == q.from_user.id))
            ).scalar_one_or_none()

            if not user_db or (user_db.credits_balance or 0) < count:
                await q.message.answer(T(lang, "insufficient_balance"))
                return

        # Show processing message
        await q.message.answer(T(lang, "processing_generation"))

        # Generate variants
        for i in range(count):
            try:
                # Create generation record
                async with db.session() as s:
                    gen_obj, user, price = await ensure_credits_and_create_generation(
                        s,
                        tg_user_id=q.from_user.id,
                        prompt=prompt,
                        scenario_key="initial_generation",
                        total_images_planned=1,
                        params={"action": action_type, "base_generation_id": generation_id},
                        source_image_urls=[base_photo["url"]],
                    )

                    if gen_obj is None:
                        await q.message.answer(T(lang, "insufficient_balance"))
                        return

                    await s.flush()
                    new_generation_id = gen_obj.id

                # Submit task
                task_id = await asyncio.to_thread(
                    seedream.create_task,
                    prompt=prompt,
                    image_urls=[base_photo["url"]],
                    image_size=image_size,
                    image_resolution=image_resolution,
                )

                # Update status
                async with db.session() as s:
                    gen_db = (
                        await s.execute(select(Generation).where(Generation.id == new_generation_id))
                    ).scalar_one_or_none()
                    if gen_db:
                        gen_db.external_id = task_id
                        gen_db.status = GenerationStatus.running

                # Poll for result
                task_info = await asyncio.to_thread(
                    seedream.wait_for_result,
                    task_id,
                    poll_interval=5.0,
                    timeout=180.0,
                )

                data_info = task_info.get("data", {})
                result_json_str = data_info.get("resultJson")
                result_obj = json.loads(result_json_str)
                result_urls = result_obj.get("resultUrls") or []

                if not result_urls:
                    raise RuntimeError(f"No result URLs")

                # Download image
                download_url = await asyncio.to_thread(seedream.get_download_url, result_urls[0])
                img_bytes = await asyncio.to_thread(seedream.download_file_bytes, download_url)

                # Update generation status
                async with db.session() as s:
                    gen_db = (
                        await s.execute(select(Generation).where(Generation.id == new_generation_id))
                    ).scalar_one_or_none()
                    if gen_db:
                        gen_db.status = GenerationStatus.succeeded
                        gen_db.images_generated = 1
                        gen_db.finished_at = datetime.now(timezone.utc)

                    # Save image
                    img = GeneratedImage(
                        generation_id=new_generation_id,
                        user_id=q.from_user.id,
                        role=ImageRole.variant,
                        storage_url=result_urls[0],
                        telegram_file_id=None,
                    )
                    s.add(img)

                # Show result with redo/continue buttons
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text=T(lang, "btn_redo_variant"), callback_data=f"angles:redo_variant:{action_type}:{count}")],
                        [InlineKeyboardButton(text=T(lang, "btn_continue_variants"), callback_data="angles:continue")],
                    ]
                )

                await q.message.answer_document(
                    document=BufferedInputFile(img_bytes, filename=f"variant_{i+1}.png"),
                    caption=T(lang, "variant_result"),
                    reply_markup=kb
                )

            except Exception as e:
                logger.exception(f"Failed to generate {action_type} variant", exc_info=e)
                async with db.session() as s:
                    gen_db = (
                        await s.execute(select(Generation).where(Generation.id == new_generation_id))
                    ).scalar_one_or_none()
                    user_db = (
                        await s.execute(select(User).where(User.user_id == q.from_user.id))
                    ).scalar_one_or_none()

                    if gen_db:
                        gen_db.status = GenerationStatus.failed
                        gen_db.error_message = str(e)
                        gen_db.finished_at = datetime.now(timezone.utc)
                    if user_db and gen_db:
                        user_db.credits_balance = (user_db.credits_balance or 0) + gen_db.credits_spent

                await q.message.answer(T(lang, "generation_failed"))


    @r.callback_query(F.data == "angles:rear")
    async def on_angles_rear_view(q: CallbackQuery, state: FSMContext):
        """Handle rear view request."""
        lang = await get_lang(q, db)
        await q.answer()

        # Ask for rear photo
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=T(lang, "btn_no_rear_photo"), callback_data="angles:rear_no_photo")],
            ]
        )

        await q.message.answer(T(lang, "rear_view_prompt"), reply_markup=kb)
        await state.set_state(GenerationFlow.waiting_rear_photo)


    @r.callback_query(F.data == "angles:rear_no_photo")
    async def on_angles_rear_no_photo(q: CallbackQuery, state: FSMContext):
        """Handle rear view without reference photo."""
        lang = await get_lang(q, db)
        await q.answer()

        data = await state.get_data()
        base_photos = data.get("base_photos", [])
        current_idx = data.get("current_base_index", 0)

        if current_idx >= len(base_photos):
            return

        base_photo = base_photos[current_idx]
        generation_id = base_photo.get("generation_id")
        aspect = base_photo.get("aspect", "3_4")
        image_size, image_resolution = ASPECT_PARAMS.get(aspect, ("768x1024", "768x1024"))

        prompt = "Change the pose and angle to a back view"

        # Generate rear view
        try:
            # Check credits and create generation
            async with db.session() as s:
                gen_obj, user, price = await ensure_credits_and_create_generation(
                    s,
                    tg_user_id=q.from_user.id,
                    prompt=prompt,
                    scenario_key="initial_generation",
                    total_images_planned=1,
                    params={"action": "rear_view_no_ref", "base_generation_id": generation_id},
                    source_image_urls=[base_photo["url"]],
                )

                if gen_obj is None:
                    await q.message.answer(T(lang, "insufficient_balance"))
                    return

                await s.flush()
                new_generation_id = gen_obj.id

            await q.message.answer(T(lang, "processing_generation"))

            # Submit task
            task_id = await asyncio.to_thread(
                seedream.create_task,
                prompt=prompt,
                image_urls=[base_photo["url"]],
                image_size=image_size,
                image_resolution=image_resolution,
            )

            async with db.session() as s:
                gen_db = (
                    await s.execute(select(Generation).where(Generation.id == new_generation_id))
                ).scalar_one_or_none()
                if gen_db:
                    gen_db.external_id = task_id
                    gen_db.status = GenerationStatus.running

            # Poll for result
            task_info = await asyncio.to_thread(seedream.wait_for_result, task_id, poll_interval=5.0, timeout=180.0)
            data_info = task_info.get("data", {})
            result_json_str = data_info.get("resultJson")
            result_obj = json.loads(result_json_str)
            result_urls = result_obj.get("resultUrls") or []

            if not result_urls:
                raise RuntimeError("No result URLs")

            # Download
            download_url = await asyncio.to_thread(seedream.get_download_url, result_urls[0])
            img_bytes = await asyncio.to_thread(seedream.download_file_bytes, download_url)

            # Update status
            async with db.session() as s:
                gen_db = (
                    await s.execute(select(Generation).where(Generation.id == new_generation_id))
                ).scalar_one_or_none()
                if gen_db:
                    gen_db.status = GenerationStatus.succeeded
                    gen_db.images_generated = 1
                    gen_db.finished_at = datetime.now(timezone.utc)

                img = GeneratedImage(
                    generation_id=new_generation_id,
                    user_id=q.from_user.id,
                    role=ImageRole.variant,
                    storage_url=result_urls[0],
                    telegram_file_id=None,
                )
                s.add(img)

            # Show result
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=T(lang, "btn_redo_variant"), callback_data="angles:redo_variant:rear_no_ref:1")],
                    [InlineKeyboardButton(text=T(lang, "btn_continue_variants"), callback_data="angles:continue")],
                ]
            )

            await q.message.answer_document(
                document=BufferedInputFile(img_bytes, filename="rear_view.png"),
                caption=T(lang, "variant_result"),
                reply_markup=kb
            )

            await state.set_state(GenerationFlow.angles_poses_menu)

        except Exception as e:
            logger.exception("Failed to generate rear view", exc_info=e)
            await q.message.answer(T(lang, "generation_failed"))


    @r.callback_query(F.data.startswith("angles:full_body") | F.data.startswith("angles:upper_body") | F.data.startswith("angles:lower_body"))
    async def on_angles_framing(q: CallbackQuery, state: FSMContext):
        """Handle framing options (full/upper/lower body)."""
        lang = await get_lang(q, db)
        await q.answer()

        # Parse action
        framing_type = q.data.split(":")[-1]  # full_body, upper_body, or lower_body

        if framing_type == "full_body":
            prompt = "Change to a full body shot"
        elif framing_type == "upper_body":
            prompt = "Change to an upper body shot"
        else:  # lower_body
            prompt = "Change to a lower body shot"

        data = await state.get_data()
        base_photos = data.get("base_photos", [])
        current_idx = data.get("current_base_index", 0)

        if current_idx >= len(base_photos):
            return

        base_photo = base_photos[current_idx]
        generation_id = base_photo.get("generation_id")
        aspect = base_photo.get("aspect", "3_4")
        image_size, image_resolution = ASPECT_PARAMS.get(aspect, ("768x1024", "768x1024"))

        try:
            async with db.session() as s:
                gen_obj, user, price = await ensure_credits_and_create_generation(
                    s,
                    tg_user_id=q.from_user.id,
                    prompt=prompt,
                    scenario_key="initial_generation",
                    total_images_planned=1,
                    params={"action": framing_type, "base_generation_id": generation_id},
                    source_image_urls=[base_photo["url"]],
                )

                if gen_obj is None:
                    await q.message.answer(T(lang, "insufficient_balance"))
                    return

                await s.flush()
                new_generation_id = gen_obj.id

            await q.message.answer(T(lang, "processing_generation"))

            task_id = await asyncio.to_thread(
                seedream.create_task,
                prompt=prompt,
                image_urls=[base_photo["url"]],
                image_size=image_size,
                image_resolution=image_resolution,
            )

            async with db.session() as s:
                gen_db = (
                    await s.execute(select(Generation).where(Generation.id == new_generation_id))
                ).scalar_one_or_none()
                if gen_db:
                    gen_db.external_id = task_id
                    gen_db.status = GenerationStatus.running

            task_info = await asyncio.to_thread(seedream.wait_for_result, task_id, poll_interval=5.0, timeout=180.0)
            data_info = task_info.get("data", {})
            result_json_str = data_info.get("resultJson")
            result_obj = json.loads(result_json_str)
            result_urls = result_obj.get("resultUrls") or []

            if not result_urls:
                raise RuntimeError("No result URLs")

            download_url = await asyncio.to_thread(seedream.get_download_url, result_urls[0])
            img_bytes = await asyncio.to_thread(seedream.download_file_bytes, download_url)

            async with db.session() as s:
                gen_db = (
                    await s.execute(select(Generation).where(Generation.id == new_generation_id))
                ).scalar_one_or_none()
                if gen_db:
                    gen_db.status = GenerationStatus.succeeded
                    gen_db.images_generated = 1
                    gen_db.finished_at = datetime.now(timezone.utc)

                img = GeneratedImage(
                    generation_id=new_generation_id,
                    user_id=q.from_user.id,
                    role=ImageRole.variant,
                    storage_url=result_urls[0],
                    telegram_file_id=None,
                )
                s.add(img)

            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=T(lang, "btn_redo_variant"), callback_data=f"angles:redo_variant:{framing_type}:1")],
                    [InlineKeyboardButton(text=T(lang, "btn_continue_variants"), callback_data="angles:continue")],
                ]
            )

            await q.message.answer_document(
                document=BufferedInputFile(img_bytes, filename=f"{framing_type}.png"),
                caption=T(lang, "variant_result"),
                reply_markup=kb
            )

        except Exception as e:
            logger.exception(f"Failed to generate {framing_type}", exc_info=e)
            await q.message.answer(T(lang, "generation_failed"))


    @r.callback_query(F.data == "angles:finish")
    async def on_angles_finish(q: CallbackQuery, state: FSMContext):
        """Handle finish button - ask for confirmation."""
        lang = await get_lang(q, db)
        await q.answer()

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=T(lang, "btn_yes_finish"), callback_data="angles:finish_confirm")],
                [InlineKeyboardButton(text=T(lang, "btn_no_continue"), callback_data="angles:finish_cancel")],
            ]
        )

        await q.message.answer(T(lang, "confirm_finish_photo"), reply_markup=kb)
        await state.set_state(GenerationFlow.confirm_finish_photo)


    @r.callback_query(F.data == "angles:finish_confirm")
    async def on_angles_finish_confirm(q: CallbackQuery, state: FSMContext):
        """Handle confirmed finish - move to next base photo or complete."""
        lang = await get_lang(q, db)
        await q.answer()

        data = await state.get_data()
        base_photos = data.get("base_photos", [])
        current_idx = data.get("current_base_index", 0)

        # Move to next base photo
        next_idx = current_idx + 1

        if next_idx >= len(base_photos):
            # All done
            await q.message.answer(T(lang, "all_base_photos_complete"))
            await state.clear()
        else:
            # Show next base photo
            await state.update_data(current_base_index=next_idx)
            await state.set_state(GenerationFlow.angles_poses_menu)
            await q.message.answer(T(lang, "moving_to_next_base"))
            await _show_angles_poses_menu(q.message, state, lang, db)


    @r.callback_query(F.data == "angles:finish_cancel")
    async def on_angles_finish_cancel(q: CallbackQuery, state: FSMContext):
        """Handle cancelled finish - return to angles menu."""
        lang = await get_lang(q, db)
        await q.answer()

        await state.set_state(GenerationFlow.angles_poses_menu)
        await _show_angles_poses_menu(q.message, state, lang, db)


    @r.callback_query(F.data == "angles:continue")
    async def on_angles_continue(q: CallbackQuery, state: FSMContext):
        """Handle continue button - return to angles menu."""
        lang = await get_lang(q, db)
        await q.answer()

        await state.set_state(GenerationFlow.angles_poses_menu)
        await _show_angles_poses_menu(q.message, state, lang, db)


    @r.message(GenerationFlow.waiting_rear_photo, F.document)
    async def on_rear_photo_upload(m: Message, state: FSMContext, bot: Bot):
        """Handle rear photo upload for rear view generation."""
        lang = await get_lang(m, db)

        # Download uploaded rear photo
        file_buf = BytesIO()
        try:
            await bot.download(file=m.document.file_id, destination=file_buf)
            file_buf.seek(0)
            rear_bytes = file_buf.read()
        except Exception as e:
            logger.exception("Failed to download rear photo", exc_info=e)
            await m.answer(T(lang, "generation_failed"))
            return

        # Upload to Seedream
        try:
            rear_url = await asyncio.to_thread(
                seedream.upload_image_bytes,
                rear_bytes,
                f"rear_{m.from_user.id}_{m.document.file_id}.jpg"
            )
        except Exception as e:
            logger.exception("Failed to upload rear photo to Seedream", exc_info=e)
            await m.answer(T(lang, "generation_failed"))
            return

        # Get base photo data
        data = await state.get_data()
        base_photos = data.get("base_photos", [])
        current_idx = data.get("current_base_index", 0)

        if current_idx >= len(base_photos):
            return

        base_photo = base_photos[current_idx]
        generation_id = base_photo.get("generation_id")
        aspect = base_photo.get("aspect", "3_4")
        image_size, image_resolution = ASPECT_PARAMS.get(aspect, ("768x1024", "768x1024"))

        prompt = "Change the pose and angle to a back view. Use the second image as a reference for how those clothes look from the back."

        # Generate rear view with reference
        try:
            async with db.session() as s:
                gen_obj, user, price = await ensure_credits_and_create_generation(
                    s,
                    tg_user_id=m.from_user.id,
                    prompt=prompt,
                    scenario_key="initial_generation",
                    total_images_planned=1,
                    params={"action": "rear_view_with_ref", "base_generation_id": generation_id},
                    source_image_urls=[base_photo["url"], rear_url],
                )

                if gen_obj is None:
                    await m.answer(T(lang, "insufficient_balance"))
                    return

                await s.flush()
                new_generation_id = gen_obj.id

            await m.answer(T(lang, "processing_generation"))

            task_id = await asyncio.to_thread(
                seedream.create_task,
                prompt=prompt,
                image_urls=[base_photo["url"], rear_url],
                image_size=image_size,
                image_resolution=image_resolution,
            )

            async with db.session() as s:
                gen_db = (
                    await s.execute(select(Generation).where(Generation.id == new_generation_id))
                ).scalar_one_or_none()
                if gen_db:
                    gen_db.external_id = task_id
                    gen_db.status = GenerationStatus.running

            task_info = await asyncio.to_thread(seedream.wait_for_result, task_id, poll_interval=5.0, timeout=180.0)
            data_info = task_info.get("data", {})
            result_json_str = data_info.get("resultJson")
            result_obj = json.loads(result_json_str)
            result_urls = result_obj.get("resultUrls") or []

            if not result_urls:
                raise RuntimeError("No result URLs")

            download_url = await asyncio.to_thread(seedream.get_download_url, result_urls[0])
            img_bytes = await asyncio.to_thread(seedream.download_file_bytes, download_url)

            async with db.session() as s:
                gen_db = (
                    await s.execute(select(Generation).where(Generation.id == new_generation_id))
                ).scalar_one_or_none()
                if gen_db:
                    gen_db.status = GenerationStatus.succeeded
                    gen_db.images_generated = 1
                    gen_db.finished_at = datetime.now(timezone.utc)

                img = GeneratedImage(
                    generation_id=new_generation_id,
                    user_id=m.from_user.id,
                    role=ImageRole.variant,
                    storage_url=result_urls[0],
                    telegram_file_id=None,
                )
                s.add(img)

            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=T(lang, "btn_redo_variant"), callback_data="angles:redo_variant:rear_with_ref:1")],
                    [InlineKeyboardButton(text=T(lang, "btn_continue_variants"), callback_data="angles:continue")],
                ]
            )

            await m.answer_document(
                document=BufferedInputFile(img_bytes, filename="rear_view_ref.png"),
                caption=T(lang, "variant_result"),
                reply_markup=kb
            )

            await state.set_state(GenerationFlow.angles_poses_menu)

        except Exception as e:
            logger.exception("Failed to generate rear view with reference", exc_info=e)
            await m.answer(T(lang, "generation_failed"))


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