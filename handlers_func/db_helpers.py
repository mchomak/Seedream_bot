# db_helpers.py
"""Database helper functions for handlers."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Any
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db import User, Transaction, TransactionStatus, Generation, GenerationStatus, ScenarioPrice, create_generation
from config import GEN_SCENARIO_PRICES


@dataclass
class Profile:
    """User profile with transaction stats and balances."""
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


async def get_scenario_price(session: AsyncSession, scenario_key: str) -> int:
    """
    Get the credit cost for a scenario from the database.
    Falls back to config.py if not found in database.
    """
    result = await session.execute(
        select(ScenarioPrice).where(
            ScenarioPrice.scenario_key == scenario_key,
            ScenarioPrice.is_active == True
        )
    )
    scenario = result.scalar_one_or_none()
    if scenario:
        return scenario.credits_cost
    # Fallback to config.py
    return GEN_SCENARIO_PRICES.get(scenario_key, 1)


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
    # Get price from database (falls back to config if not in DB)
    price = await get_scenario_price(session, scenario_key)

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