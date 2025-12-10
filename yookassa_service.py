"""
YooKassa payment service
Simple integration following YooKassa SDK best practices
"""

import os
import uuid
import logging
from typing import Optional

try:
    from yookassa import Configuration, Payment
except ImportError:
    Configuration = None
    Payment = None

logger = logging.getLogger(__name__)


class YooKassaService:
    """Simple YooKassa payment service."""

    def __init__(self):
        """Initialize YooKassa configuration."""
        self.enabled = False

        if Configuration is None or Payment is None:
            logger.warning("YooKassa SDK not installed. Install with: pip install yookassa")
            return

        # Load credentials from environment
        shop_id = os.getenv("YOOKASSA_SHOP_ID")
        secret_key = os.getenv("YOOKASSA_SECRET_KEY")
        self.return_url = os.getenv("YOOKASSA_RETURN_URL", "https://t.me/your_bot")

        if not shop_id or not secret_key:
            logger.warning(
                "YooKassa credentials not configured. "
                "Set YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY in .env"
            )
            return

        try:
            # Configure YooKassa (using property assignment as per SDK docs)
            Configuration.account_id = shop_id
            Configuration.secret_key = secret_key
            self.enabled = True
            logger.info("YooKassa service initialized successfully")
        except Exception as e:
            logger.error(f"Failed to configure YooKassa: {e}")

    def create_payment(
        self,
        amount: str,
        currency: str,
        description: str,
        user_id: Optional[int] = None,
    ) -> Optional[dict]:
        """
        Create a payment in YooKassa.

        Args:
            amount: Payment amount (e.g., "100.00")
            currency: Currency code (e.g., "RUB")
            description: Payment description
            user_id: Telegram user ID (optional, for tracking)

        Returns:
            Payment object dict with id, status, confirmation_url, etc.
            None if failed
        """
        if not self.enabled:
            logger.error("YooKassa service is not enabled")
            return None

        try:
            # Generate unique idempotence key
            idempotence_key = str(uuid.uuid4())

            # Create payment
            payment = Payment.create(
                {
                    "amount": {"value": amount, "currency": currency},
                    "confirmation": {
                        "type": "redirect",
                        "return_url": self.return_url,
                    },
                    "capture": True,  # Automatic capture
                    "description": description,
                    "metadata": {"user_id": str(user_id)} if user_id else {},
                },
                idempotence_key,
            )

            logger.info(
                f"Created payment {payment.id} for amount {amount} {currency}"
                + (f" (user {user_id})" if user_id else "")
            )

            return {
                "id": payment.id,
                "status": payment.status,
                "amount": payment.amount.value,
                "currency": payment.amount.currency,
                "description": payment.description,
                "confirmation_url": payment.confirmation.confirmation_url,
                "created_at": str(payment.created_at),
                "paid": payment.paid,
            }

        except Exception as e:
            logger.exception(f"Failed to create payment: {e}")
            return None

    def get_payment_status(self, payment_id: str) -> Optional[dict]:
        """
        Get payment status by ID.

        Args:
            payment_id: Payment ID from YooKassa

        Returns:
            Payment object dict with current status
            None if failed
        """
        if not self.enabled:
            logger.error("YooKassa service is not enabled")
            return None

        try:
            payment = Payment.find_one(payment_id)

            logger.info(f"Payment {payment_id} status: {payment.status}, paid: {payment.paid}")

            return {
                "id": payment.id,
                "status": payment.status,
                "amount": payment.amount.value,
                "currency": payment.amount.currency,
                "description": payment.description,
                "paid": payment.paid,
                "created_at": str(payment.created_at),
                "metadata": dict(payment.metadata) if payment.metadata else {},
            }

        except Exception as e:
            logger.exception(f"Failed to get payment status: {e}")
            return None
