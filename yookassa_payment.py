"""YooKassa payment integration for Telegram bot."""

import os
import uuid
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional
import logging

from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

try:
    from yookassa import Configuration, Payment
except ImportError:
    Configuration = None
    Payment = None

from db import Database, TransactionKind, TransactionStatus, User, Transaction, record_transaction, upsert_user_basic
from sqlalchemy import select


logger = logging.getLogger(__name__)


class YooKassaPay:
    """YooKassa payment helper for rubles."""

    def __init__(self, db: Database):
        self.db = db
        self.enabled = False

        # Check if YooKassa SDK is installed
        if Configuration is None or Payment is None:
            logger.warning("YooKassa SDK not installed. Install with: pip install yookassa")
            return

        # Load credentials from environment
        shop_id = os.getenv("YOOKASSA_SHOP_ID")
        secret_key = os.getenv("YOOKASSA_SECRET_KEY")
        self.return_url = os.getenv("YOOKASSA_RETURN_URL", "https://t.me/your_bot")

        if not shop_id or not secret_key:
            logger.warning("YooKassa credentials not configured. Set YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY in .env")
            return

        try:
            Configuration.configure(shop_id, secret_key)
            self.enabled = True
            logger.info("YooKassa payment service initialized successfully")
        except Exception as e:
            logger.error(f"Failed to configure YooKassa: {e}")

    async def create_payment(
        self,
        m: Message,
        state: FSMContext,
        *,
        amount_rubles: float,
        description: str,
    ) -> Optional[str]:
        """
        Create a YooKassa payment and return payment URL.

        Returns:
            Payment URL if successful, None if failed
        """
        if not self.enabled:
            await m.answer("❌ YooKassa payment is not configured")
            return None

        try:
            # Generate unique payment ID
            payment_id = str(uuid.uuid4())
            user_id = m.from_user.id if m.from_user else None

            # Create payment request
            payment = Payment.create({
                "amount": {
                    "value": f"{amount_rubles:.2f}",
                    "currency": "RUB"
                },
                "confirmation": {
                    "type": "redirect",
                    "return_url": self.return_url
                },
                "capture": True,
                "description": description,
                "metadata": {
                    "user_id": str(user_id),
                    "telegram_username": m.from_user.username if m.from_user else None,
                }
            })

            # Store payment info in database
            async with self.db.session() as s:
                await record_transaction(
                    s,
                    user_id=user_id,
                    kind=TransactionKind.purchase,
                    amount=Decimal(amount_rubles),
                    currency="RUB",
                    provider="yookassa",
                    status=TransactionStatus.pending,
                    title=description,
                    external_id=payment.id,
                    meta={
                        "payment_id": payment.id,
                        "status": payment.status,
                    },
                )

            # Store payment info in FSM
            await state.update_data(
                yookassa_payment_id=payment.id,
                yookassa_amount=amount_rubles,
            )

            # Get confirmation URL
            confirmation_url = payment.confirmation.confirmation_url
            logger.info(f"Created YooKassa payment {payment.id} for user {user_id}, amount {amount_rubles} RUB")

            return confirmation_url

        except Exception as e:
            logger.exception(f"Failed to create YooKassa payment: {e}")
            await m.answer(f"❌ Failed to create payment: {str(e)}")
            return None

    async def send_payment_link(
        self,
        m: Message,
        state: FSMContext,
        *,
        amount_rubles: float,
        description: str,
    ) -> None:
        """Create payment and send payment link to user."""
        payment_url = await self.create_payment(
            m, state, amount_rubles=amount_rubles, description=description
        )

        if payment_url:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="💳 Pay with YooKassa", url=payment_url)],
                ]
            )
            await m.answer(
                f"💰 <b>Payment Details</b>\n\n"
                f"Amount: <b>{amount_rubles:.2f} ₽</b>\n"
                f"Description: {description}\n\n"
                f"Click the button below to proceed with payment:",
                reply_markup=kb
            )

    async def check_payment_status(self, payment_id: str) -> Optional[dict]:
        """
        Check payment status by payment ID.

        Returns:
            Payment info dict with status, amount, etc. or None if failed
        """
        if not self.enabled:
            return None

        try:
            payment = Payment.find_one(payment_id)
            return {
                "id": payment.id,
                "status": payment.status,
                "paid": payment.paid,
                "amount": float(payment.amount.value),
                "currency": payment.amount.currency,
                "created_at": payment.created_at,
                "metadata": payment.metadata,
            }
        except Exception as e:
            logger.exception(f"Failed to check payment status: {e}")
            return None

    async def handle_webhook_notification(self, notification_data: dict) -> bool:
        """
        Handle YooKassa webhook notification.

        Args:
            notification_data: Parsed JSON from webhook request

        Returns:
            True if processed successfully, False otherwise
        """
        if not self.enabled:
            return False

        try:
            event_type = notification_data.get("event")
            payment_obj = notification_data.get("object")

            if not payment_obj or event_type != "payment.succeeded":
                logger.info(f"Ignoring YooKassa event: {event_type}")
                return True

            payment_id = payment_obj.get("id")
            status = payment_obj.get("status")
            paid = payment_obj.get("paid", False)
            amount_value = payment_obj.get("amount", {}).get("value")
            metadata = payment_obj.get("metadata", {})

            if not paid or status != "succeeded":
                logger.warning(f"Payment {payment_id} not succeeded: status={status}, paid={paid}")
                return True

            user_id = metadata.get("user_id")
            if user_id:
                user_id = int(user_id)

            amount_rubles = Decimal(amount_value)

            # Update transaction and user balance
            async with self.db.session() as s:
                # Update transaction status
                result = await s.execute(
                    select(Transaction).where(Transaction.external_id == payment_id)
                )
                tx = result.scalar_one_or_none()

                if tx:
                    tx.status = TransactionStatus.succeeded
                else:
                    # Create transaction if not exists (webhook arrived before we stored it)
                    await record_transaction(
                        s,
                        user_id=user_id,
                        kind=TransactionKind.purchase,
                        amount=amount_rubles,
                        currency="RUB",
                        provider="yookassa",
                        status=TransactionStatus.succeeded,
                        title="YooKassa payment",
                        external_id=payment_id,
                        meta=metadata,
                    )

                # Update user balance (convert rubles to credits)
                # You can adjust the conversion rate as needed
                if user_id:
                    db_user = (
                        await s.execute(select(User).where(User.user_id == user_id))
                    ).scalar_one_or_none()

                    if db_user:
                        # Example: 1 ruble = 1 credit (adjust as needed)
                        credits_to_add = int(amount_rubles)
                        db_user.credits_balance = (db_user.credits_balance or 0) + credits_to_add
                        logger.info(f"Added {credits_to_add} credits to user {user_id} from YooKassa payment {payment_id}")

                await s.commit()

            logger.info(f"Successfully processed YooKassa payment {payment_id}")
            return True

        except Exception as e:
            logger.exception(f"Failed to handle YooKassa webhook: {e}")
            return False
