# handlers.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Any

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
from fsm import PaymentFlow, set_waiting_payment, PaymentGuard
from seedream_service import SeedreamService
from config import *
import asyncio
import json
from io import BytesIO

# Import helper functions from modular structure
from handlers.i18n_helpers import get_lang, T, T_item, install_bot_commands
from handlers.db_helpers import Profile, get_profile, ensure_credits_and_create_generation
from handlers.keyboards import (
    build_lang_kb as _build_lang_kb,
    build_background_keyboard,
    build_hair_keyboard,
    build_style_keyboard,
    build_aspect_keyboard,
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

        # --- 14. отправляем пользователю все картинки и связываем с telegram_file_id ---
        from aiogram.types import BufferedInputFile

        sent_messages: list[tuple[str, Any]] = []

        for idx, rec in enumerate(image_records, start=1):
            caption = T(lang, "generation_done") if idx == 1 else None
            msg = await q.message.answer_photo(
                photo=BufferedInputFile(
                    rec["bytes"], filename=f"seedream_initial_{idx}.png"
                ),
                caption=caption,
            )
            sent_messages.append((rec["url"], msg))

        async with db.session() as s:
            for url, msg in sent_messages:
                if not msg.photo:
                    continue
                tele_file_id = msg.photo[-1].file_id
                img_db: Optional[GeneratedImage] = (
                    await s.execute(
                        select(GeneratedImage).where(
                            GeneratedImage.user_id == q.from_user.id,
                            GeneratedImage.storage_url == url,
                        )
                    )
                ).scalar_one_or_none()
                if img_db:
                    img_db.telegram_file_id = tele_file_id

        await state.clear()

        try:
            await q.message.edit_text(T(lang, "generation_done"))
        except Exception:
            pass


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
