# db_helpers.py
"""Database helper functions for handlers."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Any, List
from sqlalchemy import select, func, asc
from sqlalchemy.ext.asyncio import AsyncSession

from db import User, Transaction, TransactionStatus, Generation, GenerationStatus, ScenarioPrice, SystemSetting, TariffPackage, create_generation
from config import GEN_SCENARIO_PRICES


# ========== System Settings Helpers ==========

async def get_system_setting(session: AsyncSession, key: str, default: str = "") -> str:
    """Get a system setting value from the database."""
    result = await session.execute(
        select(SystemSetting).where(SystemSetting.key == key)
    )
    setting = result.scalar_one_or_none()
    return setting.value if setting else default


async def get_free_generations_limit(session: AsyncSession) -> int:
    """Get the number of free generations allowed for new users."""
    value = await get_system_setting(session, "free_generations", "3")
    try:
        return int(value)
    except ValueError:
        return 3


async def get_single_credit_price_rub(session: AsyncSession) -> Decimal:
    """Get the price of 1 credit in rubles."""
    value = await get_system_setting(session, "single_credit_price_rub", "10")
    try:
        return Decimal(value)
    except:
        return Decimal("10")


async def get_stars_to_rub_rate(session: AsyncSession) -> Decimal:
    """Get the exchange rate: 1 Telegram Star = X rubles."""
    value = await get_system_setting(session, "stars_to_rub_rate", "1.5")
    try:
        return Decimal(value)
    except:
        return Decimal("1.5")


def calculate_stars_for_rubles(rubles: Decimal, stars_to_rub_rate: Decimal) -> int:
    """Calculate the number of Stars needed for a given amount in rubles."""
    if stars_to_rub_rate <= 0:
        stars_to_rub_rate = Decimal("1.5")
    stars = rubles / stars_to_rub_rate
    # Round up to ensure we don't charge less than the price
    return int(stars.to_integral_value(rounding='ROUND_CEILING'))


# ========== Tariff Helpers ==========

async def get_active_tariffs(session: AsyncSession) -> List[TariffPackage]:
    """Get all active tariff packages sorted by sort_order."""
    result = await session.execute(
        select(TariffPackage)
        .where(TariffPackage.is_active == True)
        .order_by(asc(TariffPackage.sort_order))
    )
    return list(result.scalars().all())


async def get_tariff_by_id(session: AsyncSession, tariff_id: int) -> Optional[TariffPackage]:
    """Get a tariff package by ID."""
    result = await session.execute(
        select(TariffPackage).where(TariffPackage.id == tariff_id)
    )
    return result.scalar_one_or_none()


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


async def check_can_generate(
    session: AsyncSession,
    *,
    tg_user_id: int,
    scenario_key: str = "initial_generation",
) -> tuple[bool, Optional[User], int, bool]:
    """
    Check if user can generate (has credits or free generations available).

    Returns (can_generate, user, price, using_free_generation).
    """
    price = await get_scenario_price(session, scenario_key)
    free_limit = await get_free_generations_limit(session)

    user = (
        await session.execute(select(User).where(User.user_id == tg_user_id))
    ).scalar_one_or_none()

    if user is None:
        return False, None, price, False

    free_used = int(user.free_generations_used or 0)
    current_balance = int(user.credits_balance or 0)

    # Check if user has free generations left
    if free_used < free_limit:
        return True, user, price, True

    # Check if user has enough credits
    if current_balance >= price:
        return True, user, price, False

    return False, user, price, False


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
    Проверить баланс (или бесплатные генерации), списать кредиты и создать Generation.

    Возвращает (generation | None, user | None, price_credits).
    Если кредитов/бесплатных генераций не хватило — generation=None.
    """
    # Get price from database (falls back to config if not in DB)
    price = await get_scenario_price(session, scenario_key)
    free_limit = await get_free_generations_limit(session)

    user = (
        await session.execute(select(User).where(User.user_id == tg_user_id))
    ).scalar_one_or_none()

    if user is None:
        return None, None, price

    free_used = int(user.free_generations_used or 0)
    current_balance = int(user.credits_balance or 0)

    using_free = False
    actual_credits_spent = price

    # Check if user has free generations left
    if free_used < free_limit:
        # Use free generation
        user.free_generations_used = free_used + 1
        using_free = True
        actual_credits_spent = 0
    elif current_balance >= price:
        # Deduct from credits balance
        user.credits_balance = current_balance - price
    else:
        # Not enough credits
        return None, user, price

    # создаём запись Generation
    generation = await create_generation(
        session,
        user_id=tg_user_id,
        prompt=prompt,
        model_name="seedream-4.0",
        params=params,
        source_image_urls=source_image_urls,
        total_images_planned=total_images_planned,
        credits_spent=actual_credits_spent,
        status=GenerationStatus.queued,
        external_id=None,
    )
    # session.add(generation) уже внутри create_generation
    return generation, user, price
