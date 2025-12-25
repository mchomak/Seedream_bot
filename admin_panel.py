"""
Web Admin Panel for Seedream Bot
FastAPI-based admin interface with user management, analytics, and financial controls
"""

import os
import secrets
import json
import subprocess
import asyncio
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional, List, Dict, Any
import csv
import io

import shutil
from fastapi import FastAPI, Request, Depends, HTTPException, status, Form, Query, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
import bcrypt
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties

from sqlalchemy import select, func, and_, or_, desc, case, extract
from sqlalchemy.ext.asyncio import AsyncSession

from db import (
    Database,
    User,
    Transaction,
    Generation,
    GeneratedImage,
    AdminUser,
    AdminActionLog,
    TransactionStatus,
    TransactionKind,
    GenerationStatus,
    SystemSetting,
    TariffPackage,
    ScenarioPrice,
    BroadcastMessage,
    Backup,
)
from config import load_env, GEN_SCENARIO_PRICES
# http://localhost:8001/admin/login

# Initialize FastAPI app
app = FastAPI(title="Seedream Admin Panel", version="2.0.0")

# Load environment
settings = load_env()

# Session middleware for authentication
SECRET_KEY = os.getenv("ADMIN_SECRET_KEY", secrets.token_urlsafe(32))
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# Templates and static files
templates = Jinja2Templates(directory="admin/templates")

# Mount static files only if directory exists
static_dir = "admin/static"
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
else:
    os.makedirs(static_dir, exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Database
db: Optional[Database] = None

# Bot instance for sending messages (created on startup using TELEGRAM_BOT_TOKEN)
bot_instance: Optional[Bot] = None


def set_bot_instance(bot):
    """Set bot instance for sending notifications."""
    global bot_instance
    bot_instance = bot


@app.on_event("startup")
async def startup():
    """Initialize database and bot on startup."""
    global db, bot_instance
    db = await Database.create(settings.database_url)
    # Initialize default settings if not exists
    await init_default_settings()

    # Create bot instance for sending messages from admin panel
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if telegram_token:
        bot_instance = Bot(
            token=telegram_token,
            default=DefaultBotProperties(parse_mode="HTML"),
        )


@app.on_event("shutdown")
async def shutdown():
    """Close database and bot on shutdown."""
    global bot_instance
    if bot_instance:
        await bot_instance.session.close()
        bot_instance = None
    if db:
        await db.close()


async def init_default_settings():
    """Initialize default system settings, scenario prices, and tariff packages."""
    async with db.session() as session:
        # Check if settings exist
        result = await session.execute(select(SystemSetting).where(SystemSetting.key == "free_generations"))
        if not result.scalar_one_or_none():
            # Add default settings
            default_settings = [
                SystemSetting(key="free_generations", value="3", description="Number of free generations for new users"),
                SystemSetting(key="base_generation_cost", value="1", description="Base cost of 1 generation in credits"),
            ]
            for s in default_settings:
                session.add(s)

        # Migrate scenario prices from config to DB if not exists
        result = await session.execute(select(ScenarioPrice).limit(1))
        if not result.scalar_one_or_none():
            for key, cost in GEN_SCENARIO_PRICES.items():
                session.add(ScenarioPrice(scenario_key=key, credits_cost=cost))

        # Initialize default tariff packages if table is empty
        result = await session.execute(select(TariffPackage).limit(1))
        if not result.scalar_one_or_none():
            default_packages = [
                TariffPackage(
                    name="Starter",
                    credits=10,
                    price=Decimal("99.00"),
                    currency="RUB",
                    sort_order=1,
                    is_active=True,
                ),
                TariffPackage(
                    name="Basic",
                    credits=30,
                    price=Decimal("249.00"),
                    currency="RUB",
                    discount_percent=17,
                    sort_order=2,
                    is_active=True,
                ),
                TariffPackage(
                    name="Standard",
                    credits=70,
                    price=Decimal("499.00"),
                    currency="RUB",
                    discount_percent=28,
                    sort_order=3,
                    is_active=True,
                ),
                TariffPackage(
                    name="Pro",
                    credits=150,
                    price=Decimal("899.00"),
                    currency="RUB",
                    discount_percent=40,
                    sort_order=4,
                    is_active=True,
                ),
                TariffPackage(
                    name="Business",
                    credits=350,
                    price=Decimal("1799.00"),
                    currency="RUB",
                    discount_percent=48,
                    sort_order=5,
                    is_active=True,
                ),
            ]
            for pkg in default_packages:
                session.add(pkg)


# ============= Authentication =============


async def get_current_admin(request: Request) -> Optional[AdminUser]:
    """Get currently logged in admin user."""
    admin_id = request.session.get("admin_id")
    if not admin_id:
        return None

    async with db.session() as session:
        result = await session.execute(
            select(AdminUser).where(AdminUser.id == admin_id, AdminUser.is_active == True)
        )
        return result.scalar_one_or_none()


async def require_admin(request: Request) -> AdminUser:
    """Require authenticated admin, redirect to login if not."""
    admin = await get_current_admin(request)
    if not admin:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/login"})
    return admin


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash."""
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))


def hash_password(password: str) -> str:
    """Hash password."""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


async def log_admin_action(
    session: AsyncSession,
    admin_id: int,
    action: str,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
):
    """Log admin action to database."""
    log = AdminActionLog(
        admin_id=admin_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details,
        ip_address=ip_address,
    )
    session.add(log)


# ============= Helper Functions =============


async def get_setting(session: AsyncSession, key: str, default: str = None) -> Optional[str]:
    """Get system setting value."""
    result = await session.execute(select(SystemSetting).where(SystemSetting.key == key))
    setting = result.scalar_one_or_none()
    return setting.value if setting else default


async def set_setting(session: AsyncSession, key: str, value: str, description: str = None):
    """Set system setting value."""
    result = await session.execute(select(SystemSetting).where(SystemSetting.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = value
        if description:
            setting.description = description
    else:
        session.add(SystemSetting(key=key, value=value, description=description))


# ============= Routes =============


@app.get("/admin/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Show login page."""
    if await get_current_admin(request):
        return RedirectResponse("/admin/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/admin/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    """Handle login form submission."""
    async with db.session() as session:
        result = await session.execute(
            select(AdminUser).where(AdminUser.username == username, AdminUser.is_active == True)
        )
        admin = result.scalar_one_or_none()

        if not admin or not verify_password(password, admin.password_hash):
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "error": "Invalid username or password"},
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        admin.last_login = datetime.now(timezone.utc)
        await session.commit()
        request.session["admin_id"] = admin.id

        return RedirectResponse("/admin/", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/admin/logout")
async def logout(request: Request):
    """Logout admin user."""
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=status.HTTP_303_SEE_OTHER)


# ============= Password Management =============


@app.get("/admin/profile", response_class=HTMLResponse)
async def admin_profile(request: Request, admin: AdminUser = Depends(require_admin)):
    """Admin profile and password change page."""
    return templates.TemplateResponse("profile.html", {"request": request, "admin": admin})


@app.post("/admin/change-password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    admin: AdminUser = Depends(require_admin),
):
    """Change admin password."""
    async with db.session() as session:
        result = await session.execute(select(AdminUser).where(AdminUser.id == admin.id))
        admin_user = result.scalar_one_or_none()

        if not verify_password(current_password, admin_user.password_hash):
            return templates.TemplateResponse(
                "profile.html",
                {"request": request, "admin": admin, "error": "Current password is incorrect"},
            )

        if new_password != confirm_password:
            return templates.TemplateResponse(
                "profile.html",
                {"request": request, "admin": admin, "error": "New passwords do not match"},
            )

        if len(new_password) < 8:
            return templates.TemplateResponse(
                "profile.html",
                {"request": request, "admin": admin, "error": "Password must be at least 8 characters"},
            )

        admin_user.password_hash = hash_password(new_password)

        await log_admin_action(
            session, admin.id, "password_change",
            target_type="admin", target_id=str(admin.id),
            ip_address=request.client.host
        )

    return templates.TemplateResponse(
        "profile.html",
        {"request": request, "admin": admin, "success": "Password changed successfully"},
    )


# ============= Dashboard with Advanced Analytics =============


@app.get("/admin/", response_class=HTMLResponse)
async def dashboard(request: Request, admin: AdminUser = Depends(require_admin)):
    """Main dashboard with comprehensive analytics."""
    async with db.session() as session:
        now = datetime.now(timezone.utc)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        seven_days_ago = now - timedelta(days=7)
        thirty_days_ago = now - timedelta(days=30)

        # Basic metrics
        total_users = await session.scalar(select(func.count(User.id)))

        # Active users by period
        active_today = await session.scalar(
            select(func.count(User.id)).where(User.last_seen_at >= today)
        )
        active_7d = await session.scalar(
            select(func.count(User.id)).where(User.last_seen_at >= seven_days_ago)
        )
        active_30d = await session.scalar(
            select(func.count(User.id)).where(User.last_seen_at >= thirty_days_ago)
        )

        # Revenue metrics
        total_revenue = await session.scalar(
            select(func.sum(Transaction.amount)).where(
                Transaction.status == TransactionStatus.succeeded,
                Transaction.kind == TransactionKind.purchase,
            )
        ) or Decimal(0)

        revenue_30d = await session.scalar(
            select(func.sum(Transaction.amount)).where(
                Transaction.status == TransactionStatus.succeeded,
                Transaction.kind == TransactionKind.purchase,
                Transaction.created_at >= thirty_days_ago,
            )
        ) or Decimal(0)

        # Transaction counts
        total_transactions = await session.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.status == TransactionStatus.succeeded,
                Transaction.kind == TransactionKind.purchase,
            )
        ) or 0

        # Average check
        avg_check = await session.scalar(
            select(func.avg(Transaction.amount)).where(
                Transaction.status == TransactionStatus.succeeded,
                Transaction.kind == TransactionKind.purchase,
            )
        ) or Decimal(0)

        # Generations metrics
        total_generations = await session.scalar(select(func.count(Generation.id)))
        successful_generations = await session.scalar(
            select(func.count(Generation.id)).where(Generation.status == GenerationStatus.succeeded)
        )

        # ARPU (Average Revenue Per User) - total revenue / total users
        arpu = float(total_revenue) / total_users if total_users > 0 else 0

        # ARPPU (Average Revenue Per Paying User)
        paying_users = await session.scalar(
            select(func.count(func.distinct(Transaction.user_id))).where(
                Transaction.status == TransactionStatus.succeeded,
                Transaction.kind == TransactionKind.purchase,
            )
        ) or 0
        arppu = float(total_revenue) / paying_users if paying_users > 0 else 0

        # LTV approximation (revenue / unique paying users for simplicity)
        ltv = arppu  # Basic LTV, can be enhanced with cohort analysis

        # Conversion metrics
        users_with_payment = paying_users
        conversion_to_payment = (users_with_payment / total_users * 100) if total_users > 0 else 0

        users_with_generation = await session.scalar(
            select(func.count(func.distinct(Generation.user_id)))
        ) or 0
        conversion_to_generation = (users_with_generation / total_users * 100) if total_users > 0 else 0

        # First generation to repeat (users with more than 1 generation)
        repeat_generators = await session.scalar(
            select(func.count()).select_from(
                select(Generation.user_id)
                .group_by(Generation.user_id)
                .having(func.count(Generation.id) > 1)
                .subquery()
            )
        ) or 0
        repeat_rate = (repeat_generators / users_with_generation * 100) if users_with_generation > 0 else 0

        # Generation success rate
        success_rate = (successful_generations / total_generations * 100) if total_generations > 0 else 0

        # Deposits and debits for period
        deposits_30d = await session.scalar(
            select(func.sum(Transaction.amount)).where(
                Transaction.status == TransactionStatus.succeeded,
                Transaction.kind == TransactionKind.purchase,
                Transaction.created_at >= thirty_days_ago,
            )
        ) or Decimal(0)

        credits_spent_30d = await session.scalar(
            select(func.sum(Generation.credits_spent)).where(
                Generation.created_at >= thirty_days_ago,
            )
        ) or 0

        # Recent transactions
        recent_txs = await session.execute(
            select(Transaction).order_by(desc(Transaction.created_at)).limit(10)
        )
        recent_transactions = recent_txs.scalars().all()

        # Recent users
        recent_users_result = await session.execute(
            select(User).order_by(desc(User.created_at)).limit(10)
        )
        recent_users = recent_users_result.scalars().all()

        # Chart data: daily revenue for last 30 days
        daily_revenue_query = await session.execute(
            select(
                func.date(Transaction.created_at).label('date'),
                func.sum(Transaction.amount).label('revenue')
            ).where(
                Transaction.status == TransactionStatus.succeeded,
                Transaction.kind == TransactionKind.purchase,
                Transaction.created_at >= thirty_days_ago,
            ).group_by(func.date(Transaction.created_at))
            .order_by(func.date(Transaction.created_at))
        )
        daily_revenue = daily_revenue_query.all()

        # Chart data: daily new users for last 30 days
        daily_users_query = await session.execute(
            select(
                func.date(User.created_at).label('date'),
                func.count(User.id).label('count')
            ).where(
                User.created_at >= thirty_days_ago,
            ).group_by(func.date(User.created_at))
            .order_by(func.date(User.created_at))
        )
        daily_users = daily_users_query.all()

        stats = {
            "total_users": total_users,
            "active_today": active_today,
            "active_7d": active_7d,
            "active_30d": active_30d,
            "total_revenue": float(total_revenue),
            "revenue_30d": float(revenue_30d),
            "total_transactions": total_transactions,
            "total_generations": total_generations,
            "successful_generations": successful_generations,
            "success_rate": round(success_rate, 2),
            "avg_check": float(avg_check),
            "arpu": round(arpu, 2),
            "arppu": round(arppu, 2),
            "ltv": round(ltv, 2),
            "paying_users": paying_users,
            "conversion_to_payment": round(conversion_to_payment, 2),
            "conversion_to_generation": round(conversion_to_generation, 2),
            "repeat_rate": round(repeat_rate, 2),
            "deposits_30d": float(deposits_30d),
            "credits_spent_30d": credits_spent_30d,
        }

        chart_data = {
            "revenue_dates": [str(r.date) for r in daily_revenue],
            "revenue_values": [float(r.revenue) for r in daily_revenue],
            "users_dates": [str(r.date) for r in daily_users],
            "users_values": [r.count for r in daily_users],
        }

        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "admin": admin,
                "stats": stats,
                "chart_data": json.dumps(chart_data),
                "recent_transactions": recent_transactions,
                "recent_users": recent_users,
            },
        )


# ============= User Management =============


@app.get("/admin/users", response_class=HTMLResponse)
async def users_list(
    request: Request,
    admin: AdminUser = Depends(require_admin),
    search: Optional[str] = Query(None),
    frozen_only: bool = Query(False),
    page: int = Query(1, ge=1),
):
    """List users with search and pagination."""
    async with db.session() as session:
        ITEMS_PER_PAGE = 50

        query = select(User)

        # Search filter
        if search:
            search_filter = or_(
                User.user_id == int(search) if search.isdigit() else False,
                User.tg_username.ilike(f"%{search}%"),
            )
            query = query.where(search_filter)

        if frozen_only:
            query = query.where(User.is_frozen == True)

        # Count total
        count_query = select(func.count()).select_from(query.subquery())
        total_users = await session.scalar(count_query)

        # Paginate
        offset = (page - 1) * ITEMS_PER_PAGE
        query = query.order_by(desc(User.created_at)).offset(offset).limit(ITEMS_PER_PAGE)

        result = await session.execute(query)
        users = result.scalars().all()

        total_pages = (total_users + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE

        return templates.TemplateResponse(
            "users.html",
            {
                "request": request,
                "admin": admin,
                "users": users,
                "search": search or "",
                "frozen_only": frozen_only,
                "page": page,
                "total_pages": total_pages,
                "total_users": total_users,
            },
        )


@app.get("/admin/users/{user_id}", response_class=HTMLResponse)
async def user_detail(
    request: Request,
    user_id: int,
    admin: AdminUser = Depends(require_admin),
):
    """View user details."""
    async with db.session() as session:
        user = await session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Get transactions
        tx_result = await session.execute(
            select(Transaction)
            .where(Transaction.user_id == user.user_id)
            .order_by(desc(Transaction.created_at))
            .limit(50)
        )
        transactions = tx_result.scalars().all()

        # Get generations
        gen_result = await session.execute(
            select(Generation)
            .where(Generation.user_id == user.user_id)
            .order_by(desc(Generation.created_at))
            .limit(50)
        )
        generations = gen_result.scalars().all()

        # Calculate available generations based on current balance
        free_gens = await get_setting(session, "free_generations", "3")

        return templates.TemplateResponse(
            "user_detail.html",
            {
                "request": request,
                "admin": admin,
                "user": user,
                "transactions": transactions,
                "generations": generations,
                "free_generations": int(free_gens) if free_gens else 3,
            },
        )


@app.post("/admin/users/{user_id}/adjust-balance")
async def adjust_balance(
    request: Request,
    user_id: int,
    amount: int = Form(...),
    reason: str = Form(...),
    admin: AdminUser = Depends(require_admin),
):
    """Manually adjust user balance."""
    async with db.session() as session:
        user = await session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        old_balance = user.credits_balance or 0
        user.credits_balance = old_balance + amount

        await log_admin_action(
            session,
            admin_id=admin.id,
            action="user_balance_adjust",
            target_type="user",
            target_id=str(user.user_id),
            details={"amount": amount, "reason": reason, "old_balance": old_balance, "new_balance": user.credits_balance},
            ip_address=request.client.host,
        )

    return RedirectResponse(f"/admin/users/{user_id}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/users/{user_id}/freeze")
async def toggle_freeze_user(
    request: Request,
    user_id: int,
    admin: AdminUser = Depends(require_admin),
):
    """Freeze or unfreeze user account."""
    async with db.session() as session:
        user = await session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user.is_frozen = not user.is_frozen
        action = "user_freeze" if user.is_frozen else "user_unfreeze"

        await log_admin_action(
            session,
            admin_id=admin.id,
            action=action,
            target_type="user",
            target_id=str(user.user_id),
            details={"is_frozen": user.is_frozen},
            ip_address=request.client.host,
        )

    return RedirectResponse(f"/admin/users/{user_id}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/users/{user_id}/send-message")
async def send_user_message(
    request: Request,
    user_id: int,
    message: str = Form(...),
    admin: AdminUser = Depends(require_admin),
):
    """Send individual message to user via bot."""
    async with db.session() as session:
        user = await session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        success = False
        error_msg = None

        if bot_instance:
            try:
                await bot_instance.send_message(user.user_id, message)
                success = True
            except Exception as e:
                error_msg = str(e)
        else:
            error_msg = "Bot not configured"

        await log_admin_action(
            session,
            admin_id=admin.id,
            action="send_user_message",
            target_type="user",
            target_id=str(user.user_id),
            details={"message": message[:100], "success": success, "error": error_msg},
            ip_address=request.client.host,
        )

    return RedirectResponse(f"/admin/users/{user_id}?msg_sent={success}", status_code=status.HTTP_303_SEE_OTHER)


# ============= Transactions Management =============


@app.get("/admin/transactions", response_class=HTMLResponse)
async def transactions_list(
    request: Request,
    admin: AdminUser = Depends(require_admin),
    user_id: Optional[int] = Query(None),
    status_filter: Optional[str] = Query(None),
    kind_filter: Optional[str] = Query(None),
    suspicious_only: bool = Query(False),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
):
    """List transactions with filters."""
    async with db.session() as session:
        ITEMS_PER_PAGE = 50

        query = select(Transaction)

        filters = []
        if user_id:
            filters.append(Transaction.user_id == user_id)
        if status_filter:
            filters.append(Transaction.status == status_filter)
        if kind_filter:
            filters.append(Transaction.kind == kind_filter)
        if suspicious_only:
            filters.append(Transaction.is_suspicious == True)
        if date_from:
            filters.append(Transaction.created_at >= datetime.fromisoformat(date_from))
        if date_to:
            filters.append(Transaction.created_at <= datetime.fromisoformat(date_to + "T23:59:59"))

        if filters:
            query = query.where(and_(*filters))

        count_query = select(func.count()).select_from(query.subquery())
        total_transactions = await session.scalar(count_query)

        offset = (page - 1) * ITEMS_PER_PAGE
        query = query.order_by(desc(Transaction.created_at)).offset(offset).limit(ITEMS_PER_PAGE)

        result = await session.execute(query)
        transactions = result.scalars().all()

        total_pages = (total_transactions + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE

        return templates.TemplateResponse(
            "transactions.html",
            {
                "request": request,
                "admin": admin,
                "transactions": transactions,
                "user_id": user_id,
                "status_filter": status_filter or "",
                "kind_filter": kind_filter or "",
                "suspicious_only": suspicious_only,
                "date_from": date_from or "",
                "date_to": date_to or "",
                "page": page,
                "total_pages": total_pages,
                "total_transactions": total_transactions,
            },
        )


@app.post("/admin/transactions/{tx_id}/suspicious")
async def mark_suspicious(
    request: Request,
    tx_id: int,
    reason: str = Form(...),
    admin: AdminUser = Depends(require_admin),
):
    """Mark transaction as suspicious."""
    async with db.session() as session:
        result = await session.execute(select(Transaction).where(Transaction.id == tx_id))
        tx = result.scalar_one_or_none()
        if not tx:
            raise HTTPException(status_code=404, detail="Transaction not found")

        tx.is_suspicious = not tx.is_suspicious
        tx.suspicious_reason = reason if tx.is_suspicious else None

        await log_admin_action(
            session,
            admin_id=admin.id,
            action="transaction_suspicious_toggle",
            target_type="transaction",
            target_id=str(tx_id),
            details={"is_suspicious": tx.is_suspicious, "reason": reason},
            ip_address=request.client.host,
        )

    return RedirectResponse("/admin/transactions", status_code=status.HTTP_303_SEE_OTHER)


# ============= Tariff Settings =============


@app.get("/admin/settings", response_class=HTMLResponse)
async def settings_page(request: Request, admin: AdminUser = Depends(require_admin)):
    """System settings and tariff configuration."""
    async with db.session() as session:
        # Get system settings
        settings_result = await session.execute(select(SystemSetting).order_by(SystemSetting.key))
        system_settings = settings_result.scalars().all()

        # Get tariff packages
        packages_result = await session.execute(
            select(TariffPackage).order_by(TariffPackage.sort_order, TariffPackage.credits)
        )
        packages = packages_result.scalars().all()

        # Get scenario prices
        scenarios_result = await session.execute(
            select(ScenarioPrice).order_by(ScenarioPrice.scenario_key)
        )
        scenarios = scenarios_result.scalars().all()

        return templates.TemplateResponse(
            "settings.html",
            {
                "request": request,
                "admin": admin,
                "settings": system_settings,
                "packages": packages,
                "scenarios": scenarios,
            },
        )


@app.post("/admin/settings/update")
async def update_setting(
    request: Request,
    key: str = Form(...),
    value: str = Form(...),
    admin: AdminUser = Depends(require_admin),
):
    """Update a system setting."""
    async with db.session() as session:
        await set_setting(session, key, value)

        await log_admin_action(
            session,
            admin_id=admin.id,
            action="setting_update",
            target_type="setting",
            target_id=key,
            details={"value": value},
            ip_address=request.client.host,
        )

    return RedirectResponse("/admin/settings", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/tariffs/add")
async def add_tariff(
    request: Request,
    name: str = Form(...),
    credits: int = Form(...),
    price: float = Form(...),
    currency: str = Form("RUB"),
    discount_percent: Optional[int] = Form(None),
    ab_test_group: Optional[str] = Form(None),
    admin: AdminUser = Depends(require_admin),
):
    """Add new tariff package."""
    async with db.session() as session:
        package = TariffPackage(
            name=name,
            credits=credits,
            price=Decimal(str(price)),
            currency=currency,
            discount_percent=discount_percent,
            ab_test_group=ab_test_group if ab_test_group else None,
        )
        session.add(package)

        await log_admin_action(
            session,
            admin_id=admin.id,
            action="tariff_add",
            target_type="tariff",
            details={"name": name, "credits": credits, "price": price},
            ip_address=request.client.host,
        )

    return RedirectResponse("/admin/settings", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/tariffs/{tariff_id}/update")
async def update_tariff(
    request: Request,
    tariff_id: int,
    name: str = Form(...),
    credits: int = Form(...),
    price: float = Form(...),
    is_active: bool = Form(False),
    admin: AdminUser = Depends(require_admin),
):
    """Update tariff package."""
    async with db.session() as session:
        result = await session.execute(select(TariffPackage).where(TariffPackage.id == tariff_id))
        package = result.scalar_one_or_none()
        if package:
            package.name = name
            package.credits = credits
            package.price = Decimal(str(price))
            package.is_active = is_active

            await log_admin_action(
                session,
                admin_id=admin.id,
                action="tariff_update",
                target_type="tariff",
                target_id=str(tariff_id),
                details={"name": name, "credits": credits, "price": price, "is_active": is_active},
                ip_address=request.client.host,
            )

    return RedirectResponse("/admin/settings", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/tariffs/{tariff_id}/delete")
async def delete_tariff(
    request: Request,
    tariff_id: int,
    admin: AdminUser = Depends(require_admin),
):
    """Delete tariff package."""
    async with db.session() as session:
        result = await session.execute(select(TariffPackage).where(TariffPackage.id == tariff_id))
        package = result.scalar_one_or_none()
        if package:
            await session.delete(package)

            await log_admin_action(
                session,
                admin_id=admin.id,
                action="tariff_delete",
                target_type="tariff",
                target_id=str(tariff_id),
                ip_address=request.client.host,
            )

    return RedirectResponse("/admin/settings", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/scenarios/{scenario_id}/update")
async def update_scenario_price(
    request: Request,
    scenario_id: int,
    credits_cost: int = Form(...),
    admin: AdminUser = Depends(require_admin),
):
    """Update scenario price."""
    async with db.session() as session:
        result = await session.execute(select(ScenarioPrice).where(ScenarioPrice.id == scenario_id))
        scenario = result.scalar_one_or_none()
        if scenario:
            old_cost = scenario.credits_cost
            scenario.credits_cost = credits_cost

            await log_admin_action(
                session,
                admin_id=admin.id,
                action="scenario_price_update",
                target_type="scenario",
                target_id=scenario.scenario_key,
                details={"old_cost": old_cost, "new_cost": credits_cost},
                ip_address=request.client.host,
            )

    return RedirectResponse("/admin/settings", status_code=status.HTTP_303_SEE_OTHER)


# ============= Broadcast Messages =============


@app.get("/admin/broadcast", response_class=HTMLResponse)
async def broadcast_page(request: Request, admin: AdminUser = Depends(require_admin)):
    """Mass notification page."""
    async with db.session() as session:
        # Get broadcast history
        broadcasts_result = await session.execute(
            select(BroadcastMessage).order_by(desc(BroadcastMessage.created_at)).limit(50)
        )
        broadcasts = broadcasts_result.scalars().all()

        # Get user counts for targeting
        total_users = await session.scalar(select(func.count(User.id)))
        active_users = await session.scalar(
            select(func.count(User.id)).where(
                User.last_seen_at >= datetime.now(timezone.utc) - timedelta(days=30)
            )
        )
        inactive_users = total_users - active_users

        return templates.TemplateResponse(
            "broadcast.html",
            {
                "request": request,
                "admin": admin,
                "broadcasts": broadcasts,
                "total_users": total_users,
                "active_users": active_users,
                "inactive_users": inactive_users,
            },
        )


async def send_broadcast_messages(broadcast_id: int, message_text: str, user_ids: List[int]):
    """Background task to send broadcast messages."""
    if not bot_instance:
        return

    async with db.session() as session:
        result = await session.execute(select(BroadcastMessage).where(BroadcastMessage.id == broadcast_id))
        broadcast = result.scalar_one_or_none()
        if not broadcast:
            return

        broadcast.status = "sending"
        broadcast.started_at = datetime.now(timezone.utc)
        await session.commit()

        sent = 0
        failed = 0
        for user_id in user_ids:
            try:
                await bot_instance.send_message(user_id, message_text)
                sent += 1
            except Exception:
                failed += 1

            # Rate limiting
            if sent % 30 == 0:
                await asyncio.sleep(1)

        broadcast.sent_count = sent
        broadcast.failed_count = failed
        broadcast.status = "completed"
        broadcast.completed_at = datetime.now(timezone.utc)
        await session.commit()


@app.post("/admin/broadcast/send")
async def send_broadcast(
    request: Request,
    background_tasks: BackgroundTasks,
    message: str = Form(...),
    target_type: str = Form("all"),
    admin: AdminUser = Depends(require_admin),
):
    """Send mass notification."""
    async with db.session() as session:
        # Get target users
        query = select(User.user_id).where(User.is_frozen == False)

        if target_type == "active":
            query = query.where(User.last_seen_at >= datetime.now(timezone.utc) - timedelta(days=30))
        elif target_type == "inactive":
            query = query.where(
                or_(
                    User.last_seen_at < datetime.now(timezone.utc) - timedelta(days=30),
                    User.last_seen_at == None
                )
            )

        result = await session.execute(query)
        user_ids = [r[0] for r in result.all()]

        # Create broadcast record
        broadcast = BroadcastMessage(
            admin_id=admin.id,
            message_text=message,
            target_type=target_type,
            total_recipients=len(user_ids),
            status="pending",
        )
        session.add(broadcast)
        await session.commit()

        broadcast_id = broadcast.id

        await log_admin_action(
            session,
            admin_id=admin.id,
            action="broadcast_send",
            target_type="broadcast",
            target_id=str(broadcast_id),
            details={"target_type": target_type, "total_recipients": len(user_ids)},
            ip_address=request.client.host,
        )

    # Send in background
    background_tasks.add_task(send_broadcast_messages, broadcast_id, message, user_ids)

    return RedirectResponse("/admin/broadcast", status_code=status.HTTP_303_SEE_OTHER)


# ============= Analytics =============


@app.get("/admin/analytics", response_class=HTMLResponse)
async def analytics_page(
    request: Request,
    admin: AdminUser = Depends(require_admin),
    period: str = Query("30d"),
):
    """Detailed analytics page."""
    async with db.session() as session:
        now = datetime.now(timezone.utc)

        if period == "7d":
            start_date = now - timedelta(days=7)
        elif period == "30d":
            start_date = now - timedelta(days=30)
        elif period == "90d":
            start_date = now - timedelta(days=90)
        else:
            start_date = now - timedelta(days=30)

        # Generation type popularity - use raw SQL to avoid GROUP BY issues
        from sqlalchemy import text
        gen_types_raw = await session.execute(
            text("""
                SELECT
                    COALESCE(params->>'scenario', 'unknown') as scenario,
                    COUNT(*) as count
                FROM generations
                WHERE created_at >= :start_date
                GROUP BY params->>'scenario'
                ORDER BY count DESC
            """),
            {"start_date": start_date}
        )
        gen_types = gen_types_raw.all()

        # Daily metrics for charts
        daily_metrics_query = await session.execute(
            select(
                func.date(Transaction.created_at).label('date'),
                func.sum(Transaction.amount).label('revenue'),
                func.count(Transaction.id).label('count')
            ).where(
                Transaction.status == TransactionStatus.succeeded,
                Transaction.kind == TransactionKind.purchase,
                Transaction.created_at >= start_date,
            ).group_by(func.date(Transaction.created_at))
            .order_by(func.date(Transaction.created_at))
        )
        daily_metrics = daily_metrics_query.all()

        # Daily generations
        daily_gens_query = await session.execute(
            select(
                func.date(Generation.created_at).label('date'),
                func.count(Generation.id).label('total'),
                func.sum(case((Generation.status == GenerationStatus.succeeded, 1), else_=0)).label('success')
            ).where(
                Generation.created_at >= start_date,
            ).group_by(func.date(Generation.created_at))
            .order_by(func.date(Generation.created_at))
        )
        daily_gens = daily_gens_query.all()

        # User cohorts - use raw SQL to avoid GROUP BY issues with date_trunc
        cohorts_raw = await session.execute(
            text("""
                SELECT
                    DATE_TRUNC('week', created_at) as cohort,
                    COUNT(*) as count
                FROM users
                WHERE created_at >= :start_date
                GROUP BY DATE_TRUNC('week', created_at)
                ORDER BY DATE_TRUNC('week', created_at)
            """),
            {"start_date": start_date}
        )
        cohorts = cohorts_raw.all()

        # Aggregate user balance
        total_credits = await session.scalar(
            select(func.sum(User.credits_balance))
        ) or 0

        chart_data = {
            "dates": [str(m.date) for m in daily_metrics],
            "revenue": [float(m.revenue or 0) for m in daily_metrics],
            "tx_count": [m.count for m in daily_metrics],
            "gen_dates": [str(g.date) for g in daily_gens],
            "gen_total": [g.total for g in daily_gens],
            "gen_success": [int(g.success or 0) for g in daily_gens],
            "gen_types": {str(g.scenario or 'unknown'): g.count for g in gen_types},
            "cohort_dates": [str(c.cohort.date()) if c.cohort else '' for c in cohorts],
            "cohort_counts": [c.count for c in cohorts],
        }

        return templates.TemplateResponse(
            "analytics.html",
            {
                "request": request,
                "admin": admin,
                "period": period,
                "chart_data": json.dumps(chart_data),
                "total_credits": total_credits,
            },
        )


# ============= Conversions =============


@app.get("/admin/conversions", response_class=HTMLResponse)
async def conversions_page(
    request: Request,
    admin: AdminUser = Depends(require_admin),
    period: str = Query("30d"),
):
    """Conversion funnel analytics page."""
    async with db.session() as session:
        now = datetime.now(timezone.utc)

        if period == "7d":
            start_date = now - timedelta(days=7)
        elif period == "30d":
            start_date = now - timedelta(days=30)
        elif period == "90d":
            start_date = now - timedelta(days=90)
        elif period == "all":
            start_date = datetime(2020, 1, 1, tzinfo=timezone.utc)
        else:
            start_date = now - timedelta(days=30)

        from sqlalchemy import text

        # ========== 1. Launch → Payment ==========
        # Total users who started the bot in this period
        total_launched = await session.scalar(
            select(func.count(User.id)).where(User.created_at >= start_date)
        ) or 0

        # Users who made at least one successful payment in this period
        users_with_payment = await session.scalar(
            select(func.count(func.distinct(Transaction.user_id))).where(
                Transaction.status == TransactionStatus.succeeded,
                Transaction.kind == TransactionKind.purchase,
                Transaction.created_at >= start_date,
            )
        ) or 0

        launch_to_payment_rate = (users_with_payment / total_launched * 100) if total_launched > 0 else 0

        # ========== 2. Balance Top-up → Use of generations ==========
        # Users who topped up balance (have successful transactions)
        users_topped_up = await session.scalar(
            select(func.count(func.distinct(Transaction.user_id))).where(
                Transaction.status == TransactionStatus.succeeded,
                Transaction.kind == TransactionKind.purchase,
                Transaction.created_at >= start_date,
            )
        ) or 0

        # Users who topped up AND then made at least one generation
        users_topped_and_generated_raw = await session.execute(
            text("""
                SELECT COUNT(DISTINCT t.user_id)
                FROM transactions t
                INNER JOIN generations g ON t.user_id = g.user_id
                WHERE t.status = 'succeeded'
                  AND t.kind = 'purchase'
                  AND t.created_at >= :start_date
                  AND g.created_at >= t.created_at
            """),
            {"start_date": start_date}
        )
        users_topped_and_generated = users_topped_and_generated_raw.scalar() or 0

        topup_to_generation_rate = (users_topped_and_generated / users_topped_up * 100) if users_topped_up > 0 else 0

        # ========== 3. First Generation → Repeat Order ==========
        # Users who made at least one generation
        users_with_generation = await session.scalar(
            select(func.count(func.distinct(Generation.user_id))).where(
                Generation.created_at >= start_date,
            )
        ) or 0

        # Users who made more than one generation (repeat)
        repeat_generators_raw = await session.execute(
            text("""
                SELECT COUNT(*) FROM (
                    SELECT user_id
                    FROM generations
                    WHERE created_at >= :start_date
                    GROUP BY user_id
                    HAVING COUNT(*) > 1
                ) as repeat_users
            """),
            {"start_date": start_date}
        )
        repeat_generators = repeat_generators_raw.scalar() or 0

        first_to_repeat_rate = (repeat_generators / users_with_generation * 100) if users_with_generation > 0 else 0

        # ========== 4. Generation Request → Finished Result ==========
        # Total generation requests
        total_generation_requests = await session.scalar(
            select(func.count(Generation.id)).where(Generation.created_at >= start_date)
        ) or 0

        # Successfully finished generations
        finished_generations = await session.scalar(
            select(func.count(Generation.id)).where(
                Generation.status == GenerationStatus.succeeded,
                Generation.created_at >= start_date,
            )
        ) or 0

        request_to_result_rate = (finished_generations / total_generation_requests * 100) if total_generation_requests > 0 else 0

        # Failed generations
        failed_generations = await session.scalar(
            select(func.count(Generation.id)).where(
                Generation.status == GenerationStatus.failed,
                Generation.created_at >= start_date,
            )
        ) or 0

        # ========== Daily conversion data for charts ==========
        # Daily launch to payment
        daily_launch_payment_raw = await session.execute(
            text("""
                WITH daily_users AS (
                    SELECT DATE(created_at) as date, COUNT(*) as launched
                    FROM users
                    WHERE created_at >= :start_date
                    GROUP BY DATE(created_at)
                ),
                daily_payers AS (
                    SELECT DATE(created_at) as date, COUNT(DISTINCT user_id) as paid
                    FROM transactions
                    WHERE status = 'succeeded' AND kind = 'purchase' AND created_at >= :start_date
                    GROUP BY DATE(created_at)
                )
                SELECT
                    COALESCE(u.date, p.date) as date,
                    COALESCE(u.launched, 0) as launched,
                    COALESCE(p.paid, 0) as paid
                FROM daily_users u
                FULL OUTER JOIN daily_payers p ON u.date = p.date
                ORDER BY date
            """),
            {"start_date": start_date}
        )
        daily_launch_payment = daily_launch_payment_raw.all()

        # Daily generation success rate
        daily_gen_success_raw = await session.execute(
            text("""
                SELECT
                    DATE(created_at) as date,
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) as succeeded,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
                FROM generations
                WHERE created_at >= :start_date
                GROUP BY DATE(created_at)
                ORDER BY date
            """),
            {"start_date": start_date}
        )
        daily_gen_success = daily_gen_success_raw.all()

        # Prepare chart data
        chart_data = {
            "launch_dates": [str(d.date) for d in daily_launch_payment],
            "launched": [d.launched for d in daily_launch_payment],
            "paid": [d.paid for d in daily_launch_payment],
            "gen_dates": [str(d.date) for d in daily_gen_success],
            "gen_total": [d.total for d in daily_gen_success],
            "gen_succeeded": [d.succeeded for d in daily_gen_success],
            "gen_failed": [d.failed for d in daily_gen_success],
        }

        # Funnel data for visualization
        funnel_data = {
            "launch_to_payment": {
                "total_launched": total_launched,
                "users_with_payment": users_with_payment,
                "rate": round(launch_to_payment_rate, 2),
            },
            "topup_to_generation": {
                "users_topped_up": users_topped_up,
                "users_used_generations": users_topped_and_generated,
                "rate": round(topup_to_generation_rate, 2),
            },
            "first_to_repeat": {
                "users_with_generation": users_with_generation,
                "repeat_generators": repeat_generators,
                "rate": round(first_to_repeat_rate, 2),
            },
            "request_to_result": {
                "total_requests": total_generation_requests,
                "finished": finished_generations,
                "failed": failed_generations,
                "rate": round(request_to_result_rate, 2),
            },
        }

        return templates.TemplateResponse(
            "conversions.html",
            {
                "request": request,
                "admin": admin,
                "period": period,
                "funnel_data": funnel_data,
                "chart_data": json.dumps(chart_data),
            },
        )


# ============= Reports =============


@app.get("/admin/reports", response_class=HTMLResponse)
async def reports_page(
    request: Request,
    admin: AdminUser = Depends(require_admin),
    period: str = Query("30d"),
):
    """Comprehensive reports page with all key metrics and export options."""
    async with db.session() as session:
        now = datetime.now(timezone.utc)

        if period == "7d":
            start_date = now - timedelta(days=7)
            period_label = "Last 7 Days"
        elif period == "30d":
            start_date = now - timedelta(days=30)
            period_label = "Last 30 Days"
        elif period == "90d":
            start_date = now - timedelta(days=90)
            period_label = "Last 90 Days"
        elif period == "all":
            start_date = datetime(2020, 1, 1, tzinfo=timezone.utc)
            period_label = "All Time"
        else:
            start_date = now - timedelta(days=30)
            period_label = "Last 30 Days"

        from sqlalchemy import text

        # ========== User Metrics ==========
        total_users = await session.scalar(select(func.count(User.id))) or 0
        new_users_period = await session.scalar(
            select(func.count(User.id)).where(User.created_at >= start_date)
        ) or 0
        active_users_period = await session.scalar(
            select(func.count(User.id)).where(User.last_seen_at >= start_date)
        ) or 0

        # ========== Financial Metrics ==========
        # Total revenue (all time)
        total_revenue = await session.scalar(
            select(func.sum(Transaction.amount)).where(
                Transaction.status == TransactionStatus.succeeded,
                Transaction.kind == TransactionKind.purchase,
            )
        ) or Decimal(0)

        # Revenue for period
        revenue_period = await session.scalar(
            select(func.sum(Transaction.amount)).where(
                Transaction.status == TransactionStatus.succeeded,
                Transaction.kind == TransactionKind.purchase,
                Transaction.created_at >= start_date,
            )
        ) or Decimal(0)

        # Transaction count
        tx_count_period = await session.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.status == TransactionStatus.succeeded,
                Transaction.kind == TransactionKind.purchase,
                Transaction.created_at >= start_date,
            )
        ) or 0

        # Average check
        avg_check = await session.scalar(
            select(func.avg(Transaction.amount)).where(
                Transaction.status == TransactionStatus.succeeded,
                Transaction.kind == TransactionKind.purchase,
                Transaction.created_at >= start_date,
            )
        ) or Decimal(0)

        # Paying users
        paying_users = await session.scalar(
            select(func.count(func.distinct(Transaction.user_id))).where(
                Transaction.status == TransactionStatus.succeeded,
                Transaction.kind == TransactionKind.purchase,
            )
        ) or 0

        paying_users_period = await session.scalar(
            select(func.count(func.distinct(Transaction.user_id))).where(
                Transaction.status == TransactionStatus.succeeded,
                Transaction.kind == TransactionKind.purchase,
                Transaction.created_at >= start_date,
            )
        ) or 0

        # ========== ARPU / ARPPU / LTV ==========
        # ARPU = Total Revenue / Total Users
        arpu = float(total_revenue) / total_users if total_users > 0 else 0

        # ARPPU = Total Revenue / Paying Users
        arppu = float(total_revenue) / paying_users if paying_users > 0 else 0

        # LTV = ARPPU (simplified, can be enhanced with cohort analysis)
        ltv = arppu

        # Period ARPU/ARPPU
        arpu_period = float(revenue_period) / new_users_period if new_users_period > 0 else 0
        arppu_period = float(revenue_period) / paying_users_period if paying_users_period > 0 else 0

        # ========== Generation Metrics ==========
        total_generations = await session.scalar(
            select(func.count(Generation.id)).where(Generation.created_at >= start_date)
        ) or 0

        successful_generations = await session.scalar(
            select(func.count(Generation.id)).where(
                Generation.status == GenerationStatus.succeeded,
                Generation.created_at >= start_date,
            )
        ) or 0

        failed_generations = await session.scalar(
            select(func.count(Generation.id)).where(
                Generation.status == GenerationStatus.failed,
                Generation.created_at >= start_date,
            )
        ) or 0

        generation_success_rate = (successful_generations / total_generations * 100) if total_generations > 0 else 0

        # ========== User Balance (Aggregated) ==========
        total_credits_balance = await session.scalar(
            select(func.sum(User.credits_balance))
        ) or 0

        avg_credits_balance = await session.scalar(
            select(func.avg(User.credits_balance))
        ) or 0

        users_with_balance = await session.scalar(
            select(func.count(User.id)).where(User.credits_balance > 0)
        ) or 0

        # ========== Conversion Metrics ==========
        # Launch → Payment
        conversion_to_payment = (paying_users / total_users * 100) if total_users > 0 else 0

        # Users with generations
        users_with_gen = await session.scalar(
            select(func.count(func.distinct(Generation.user_id)))
        ) or 0
        conversion_to_generation = (users_with_gen / total_users * 100) if total_users > 0 else 0

        # ========== Generation Types Popularity ==========
        gen_types_raw = await session.execute(
            text("""
                SELECT
                    COALESCE(params->>'scenario', 'unknown') as scenario,
                    COUNT(*) as count
                FROM generations
                WHERE created_at >= :start_date
                GROUP BY params->>'scenario'
                ORDER BY count DESC
                LIMIT 10
            """),
            {"start_date": start_date}
        )
        gen_types = gen_types_raw.all()

        # ========== Daily Revenue Data ==========
        daily_revenue_raw = await session.execute(
            text("""
                SELECT
                    DATE(created_at) as date,
                    SUM(amount) as revenue,
                    COUNT(*) as tx_count
                FROM transactions
                WHERE status = 'succeeded' AND kind = 'purchase' AND created_at >= :start_date
                GROUP BY DATE(created_at)
                ORDER BY date
            """),
            {"start_date": start_date}
        )
        daily_revenue = daily_revenue_raw.all()

        # ========== Daily User Growth ==========
        daily_users_raw = await session.execute(
            text("""
                SELECT
                    DATE(created_at) as date,
                    COUNT(*) as new_users,
                    SUM(COUNT(*)) OVER (ORDER BY DATE(created_at)) as cumulative
                FROM users
                WHERE created_at >= :start_date
                GROUP BY DATE(created_at)
                ORDER BY date
            """),
            {"start_date": start_date}
        )
        daily_users = daily_users_raw.all()

        # Prepare all data
        report_data = {
            "period": period,
            "period_label": period_label,
            "generated_at": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "users": {
                "total": total_users,
                "new_period": new_users_period,
                "active_period": active_users_period,
                "with_balance": users_with_balance,
            },
            "financial": {
                "total_revenue": float(total_revenue),
                "revenue_period": float(revenue_period),
                "tx_count_period": tx_count_period,
                "avg_check": round(float(avg_check), 2),
                "paying_users_total": paying_users,
                "paying_users_period": paying_users_period,
            },
            "unit_economics": {
                "arpu": round(arpu, 2),
                "arppu": round(arppu, 2),
                "ltv": round(ltv, 2),
                "arpu_period": round(arpu_period, 2),
                "arppu_period": round(arppu_period, 2),
            },
            "generations": {
                "total": total_generations,
                "successful": successful_generations,
                "failed": failed_generations,
                "success_rate": round(generation_success_rate, 2),
            },
            "balance": {
                "total_credits": total_credits_balance,
                "avg_credits": round(float(avg_credits_balance), 2),
                "users_with_balance": users_with_balance,
            },
            "conversions": {
                "to_payment": round(conversion_to_payment, 2),
                "to_generation": round(conversion_to_generation, 2),
            },
            "gen_types": [{"scenario": g.scenario, "count": g.count} for g in gen_types],
        }

        chart_data = {
            "revenue_dates": [str(d.date) for d in daily_revenue],
            "revenue_values": [float(d.revenue) for d in daily_revenue],
            "tx_counts": [d.tx_count for d in daily_revenue],
            "users_dates": [str(d.date) for d in daily_users],
            "new_users": [d.new_users for d in daily_users],
            "cumulative_users": [d.cumulative for d in daily_users],
            "gen_types_labels": [g.scenario for g in gen_types],
            "gen_types_values": [g.count for g in gen_types],
        }

        return templates.TemplateResponse(
            "reports.html",
            {
                "request": request,
                "admin": admin,
                "period": period,
                "report_data": report_data,
                "chart_data": json.dumps(chart_data),
            },
        )


@app.get("/admin/reports/export/csv")
async def export_report_csv(
    admin: AdminUser = Depends(require_admin),
    period: str = Query("30d"),
):
    """Export comprehensive report as CSV."""
    async with db.session() as session:
        now = datetime.now(timezone.utc)

        if period == "7d":
            start_date = now - timedelta(days=7)
        elif period == "30d":
            start_date = now - timedelta(days=30)
        elif period == "90d":
            start_date = now - timedelta(days=90)
        else:
            start_date = datetime(2020, 1, 1, tzinfo=timezone.utc)

        from sqlalchemy import text

        # Gather all metrics
        total_users = await session.scalar(select(func.count(User.id))) or 0
        new_users = await session.scalar(
            select(func.count(User.id)).where(User.created_at >= start_date)
        ) or 0
        active_users = await session.scalar(
            select(func.count(User.id)).where(User.last_seen_at >= start_date)
        ) or 0

        total_revenue = await session.scalar(
            select(func.sum(Transaction.amount)).where(
                Transaction.status == TransactionStatus.succeeded,
                Transaction.kind == TransactionKind.purchase,
            )
        ) or Decimal(0)

        revenue_period = await session.scalar(
            select(func.sum(Transaction.amount)).where(
                Transaction.status == TransactionStatus.succeeded,
                Transaction.kind == TransactionKind.purchase,
                Transaction.created_at >= start_date,
            )
        ) or Decimal(0)

        avg_check = await session.scalar(
            select(func.avg(Transaction.amount)).where(
                Transaction.status == TransactionStatus.succeeded,
                Transaction.kind == TransactionKind.purchase,
            )
        ) or Decimal(0)

        paying_users = await session.scalar(
            select(func.count(func.distinct(Transaction.user_id))).where(
                Transaction.status == TransactionStatus.succeeded,
                Transaction.kind == TransactionKind.purchase,
            )
        ) or 0

        total_generations = await session.scalar(
            select(func.count(Generation.id)).where(Generation.created_at >= start_date)
        ) or 0

        successful_gens = await session.scalar(
            select(func.count(Generation.id)).where(
                Generation.status == GenerationStatus.succeeded,
                Generation.created_at >= start_date,
            )
        ) or 0

        total_credits = await session.scalar(
            select(func.sum(User.credits_balance))
        ) or 0

        # Calculate derived metrics
        arpu = float(total_revenue) / total_users if total_users > 0 else 0
        arppu = float(total_revenue) / paying_users if paying_users > 0 else 0
        success_rate = (successful_gens / total_generations * 100) if total_generations > 0 else 0
        conversion = (paying_users / total_users * 100) if total_users > 0 else 0

        # Create CSV
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow(["Seedream Bot Analytics Report"])
        writer.writerow([f"Period: {period}"])
        writer.writerow([f"Generated: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}"])
        writer.writerow([])

        writer.writerow(["=== USER METRICS ==="])
        writer.writerow(["Metric", "Value"])
        writer.writerow(["Total Users", total_users])
        writer.writerow(["New Users (Period)", new_users])
        writer.writerow(["Active Users (Period)", active_users])
        writer.writerow([])

        writer.writerow(["=== FINANCIAL METRICS ==="])
        writer.writerow(["Metric", "Value"])
        writer.writerow(["Total Revenue (All Time)", f"{float(total_revenue):.2f}"])
        writer.writerow(["Revenue (Period)", f"{float(revenue_period):.2f}"])
        writer.writerow(["Average Check", f"{float(avg_check):.2f}"])
        writer.writerow(["Paying Users", paying_users])
        writer.writerow([])

        writer.writerow(["=== UNIT ECONOMICS ==="])
        writer.writerow(["Metric", "Value"])
        writer.writerow(["ARPU", f"{arpu:.2f}"])
        writer.writerow(["ARPPU", f"{arppu:.2f}"])
        writer.writerow(["LTV", f"{arppu:.2f}"])
        writer.writerow(["Conversion to Payment", f"{conversion:.2f}%"])
        writer.writerow([])

        writer.writerow(["=== GENERATION METRICS ==="])
        writer.writerow(["Metric", "Value"])
        writer.writerow(["Total Generations (Period)", total_generations])
        writer.writerow(["Successful Generations", successful_gens])
        writer.writerow(["Success Rate", f"{success_rate:.2f}%"])
        writer.writerow([])

        writer.writerow(["=== BALANCE METRICS ==="])
        writer.writerow(["Metric", "Value"])
        writer.writerow(["Total Credits in System", total_credits])

        # Add daily breakdown
        writer.writerow([])
        writer.writerow(["=== DAILY REVENUE ==="])
        writer.writerow(["Date", "Revenue", "Transactions"])

        daily_raw = await session.execute(
            text("""
                SELECT DATE(created_at) as date, SUM(amount) as revenue, COUNT(*) as count
                FROM transactions
                WHERE status = 'succeeded' AND kind = 'purchase' AND created_at >= :start_date
                GROUP BY DATE(created_at) ORDER BY date
            """),
            {"start_date": start_date}
        )
        for row in daily_raw.all():
            writer.writerow([str(row.date), f"{float(row.revenue):.2f}", row.count])

        output.seek(0)
        filename = f"seedream_report_{period}_{now.strftime('%Y%m%d')}.csv"

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv; charset=utf-8-sig",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )


@app.get("/admin/reports/print", response_class=HTMLResponse)
async def print_report(
    request: Request,
    admin: AdminUser = Depends(require_admin),
    period: str = Query("30d"),
):
    """Printable report view (can be saved as PDF via browser)."""
    async with db.session() as session:
        now = datetime.now(timezone.utc)

        if period == "7d":
            start_date = now - timedelta(days=7)
            period_label = "Last 7 Days"
        elif period == "30d":
            start_date = now - timedelta(days=30)
            period_label = "Last 30 Days"
        elif period == "90d":
            start_date = now - timedelta(days=90)
            period_label = "Last 90 Days"
        else:
            start_date = datetime(2020, 1, 1, tzinfo=timezone.utc)
            period_label = "All Time"

        from sqlalchemy import text

        # Gather all metrics (same as reports_page)
        total_users = await session.scalar(select(func.count(User.id))) or 0
        new_users = await session.scalar(
            select(func.count(User.id)).where(User.created_at >= start_date)
        ) or 0
        active_users = await session.scalar(
            select(func.count(User.id)).where(User.last_seen_at >= start_date)
        ) or 0

        total_revenue = await session.scalar(
            select(func.sum(Transaction.amount)).where(
                Transaction.status == TransactionStatus.succeeded,
                Transaction.kind == TransactionKind.purchase,
            )
        ) or Decimal(0)

        revenue_period = await session.scalar(
            select(func.sum(Transaction.amount)).where(
                Transaction.status == TransactionStatus.succeeded,
                Transaction.kind == TransactionKind.purchase,
                Transaction.created_at >= start_date,
            )
        ) or Decimal(0)

        avg_check = await session.scalar(
            select(func.avg(Transaction.amount)).where(
                Transaction.status == TransactionStatus.succeeded,
                Transaction.kind == TransactionKind.purchase,
            )
        ) or Decimal(0)

        paying_users = await session.scalar(
            select(func.count(func.distinct(Transaction.user_id))).where(
                Transaction.status == TransactionStatus.succeeded,
                Transaction.kind == TransactionKind.purchase,
            )
        ) or 0

        total_generations = await session.scalar(
            select(func.count(Generation.id)).where(Generation.created_at >= start_date)
        ) or 0

        successful_gens = await session.scalar(
            select(func.count(Generation.id)).where(
                Generation.status == GenerationStatus.succeeded,
                Generation.created_at >= start_date,
            )
        ) or 0

        failed_gens = await session.scalar(
            select(func.count(Generation.id)).where(
                Generation.status == GenerationStatus.failed,
                Generation.created_at >= start_date,
            )
        ) or 0

        total_credits = await session.scalar(
            select(func.sum(User.credits_balance))
        ) or 0

        users_with_balance = await session.scalar(
            select(func.count(User.id)).where(User.credits_balance > 0)
        ) or 0

        # Calculate derived metrics
        arpu = float(total_revenue) / total_users if total_users > 0 else 0
        arppu = float(total_revenue) / paying_users if paying_users > 0 else 0
        success_rate = (successful_gens / total_generations * 100) if total_generations > 0 else 0
        conversion = (paying_users / total_users * 100) if total_users > 0 else 0

        # Generation types
        gen_types_raw = await session.execute(
            text("""
                SELECT COALESCE(params->>'scenario', 'unknown') as scenario, COUNT(*) as count
                FROM generations WHERE created_at >= :start_date
                GROUP BY params->>'scenario' ORDER BY count DESC LIMIT 10
            """),
            {"start_date": start_date}
        )
        gen_types = gen_types_raw.all()

        report_data = {
            "period_label": period_label,
            "generated_at": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "total_users": total_users,
            "new_users": new_users,
            "active_users": active_users,
            "total_revenue": float(total_revenue),
            "revenue_period": float(revenue_period),
            "avg_check": round(float(avg_check), 2),
            "paying_users": paying_users,
            "arpu": round(arpu, 2),
            "arppu": round(arppu, 2),
            "ltv": round(arppu, 2),
            "conversion": round(conversion, 2),
            "total_generations": total_generations,
            "successful_gens": successful_gens,
            "failed_gens": failed_gens,
            "success_rate": round(success_rate, 2),
            "total_credits": total_credits,
            "users_with_balance": users_with_balance,
            "gen_types": [{"scenario": g.scenario, "count": g.count} for g in gen_types],
        }

        return templates.TemplateResponse(
            "report_print.html",
            {
                "request": request,
                "report": report_data,
            },
        )


# ============= Export =============


@app.get("/admin/export/users")
async def export_users(
    admin: AdminUser = Depends(require_admin),
    format: str = Query("csv"),
):
    """Export users to CSV or Excel."""
    async with db.session() as session:
        result = await session.execute(select(User).order_by(User.created_at))
        users = result.scalars().all()

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "ID", "Telegram ID", "Username", "Language", "Credits", "Money Balance",
            "Is Premium", "Is Frozen", "AB Group", "Created At", "Last Seen", "First Payment", "First Generation"
        ])

        for user in users:
            writer.writerow([
                user.id,
                user.user_id,
                user.tg_username or "",
                user.lang or "",
                user.credits_balance or 0,
                float(user.money_balance or 0),
                user.is_premium,
                user.is_frozen,
                user.ab_test_group or "",
                user.created_at.isoformat() if user.created_at else "",
                user.last_seen_at.isoformat() if user.last_seen_at else "",
                user.first_payment_at.isoformat() if user.first_payment_at else "",
                user.first_generation_at.isoformat() if user.first_generation_at else "",
            ])

        output.seek(0)

        if format == "excel":
            # For Excel, we'd need openpyxl, return CSV for now with Excel-compatible encoding
            return StreamingResponse(
                iter([output.getvalue()]),
                media_type="text/csv; charset=utf-8-sig",
                headers={"Content-Disposition": "attachment; filename=users.csv"},
            )

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=users.csv"},
        )


@app.get("/admin/export/transactions")
async def export_transactions(
    admin: AdminUser = Depends(require_admin),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    format: str = Query("csv"),
):
    """Export transactions to CSV or Excel."""
    async with db.session() as session:
        query = select(Transaction).order_by(Transaction.created_at)

        if date_from:
            query = query.where(Transaction.created_at >= datetime.fromisoformat(date_from))
        if date_to:
            query = query.where(Transaction.created_at <= datetime.fromisoformat(date_to + "T23:59:59"))

        result = await session.execute(query)
        transactions = result.scalars().all()

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "ID", "User ID", "Amount", "Currency", "Status", "Kind",
            "Provider", "Is Suspicious", "Suspicious Reason", "Created At"
        ])

        for tx in transactions:
            writer.writerow([
                tx.id,
                tx.user_id or "",
                float(tx.amount),
                tx.currency,
                tx.status.value,
                tx.kind.value,
                tx.provider or "",
                tx.is_suspicious,
                tx.suspicious_reason or "",
                tx.created_at.isoformat() if tx.created_at else "",
            ])

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=transactions.csv"},
        )


@app.get("/admin/export/generations")
async def export_generations(
    admin: AdminUser = Depends(require_admin),
    format: str = Query("csv"),
):
    """Export generations to CSV."""
    async with db.session() as session:
        result = await session.execute(select(Generation).order_by(Generation.created_at))
        generations = result.scalars().all()

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "ID", "User ID", "Status", "Credits Spent", "Images Generated",
            "Model", "Created At", "Finished At"
        ])

        for gen in generations:
            writer.writerow([
                gen.id,
                gen.user_id,
                gen.status.value,
                gen.credits_spent,
                gen.images_generated,
                gen.model_name,
                gen.created_at.isoformat() if gen.created_at else "",
                gen.finished_at.isoformat() if gen.finished_at else "",
            ])

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=generations.csv"},
        )


# ============= Admin Logs =============


@app.get("/admin/logs", response_class=HTMLResponse)
async def admin_logs(
    request: Request,
    admin: AdminUser = Depends(require_admin),
    action_filter: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
):
    """View admin action logs."""
    async with db.session() as session:
        ITEMS_PER_PAGE = 50

        query = select(AdminActionLog)
        if action_filter:
            query = query.where(AdminActionLog.action.ilike(f"%{action_filter}%"))

        total_logs = await session.scalar(select(func.count()).select_from(query.subquery()))

        offset = (page - 1) * ITEMS_PER_PAGE
        result = await session.execute(
            query.order_by(desc(AdminActionLog.created_at))
            .offset(offset)
            .limit(ITEMS_PER_PAGE)
        )
        logs = result.scalars().all()

        total_pages = (total_logs + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE

        return templates.TemplateResponse(
            "logs.html",
            {
                "request": request,
                "admin": admin,
                "logs": logs,
                "action_filter": action_filter or "",
                "page": page,
                "total_pages": total_pages,
            },
        )


# ============= Backup =============


@app.get("/admin/backups", response_class=HTMLResponse)
async def backups_page(request: Request, admin: AdminUser = Depends(require_admin)):
    """Database backup management."""
    async with db.session() as session:
        result = await session.execute(
            select(Backup).order_by(desc(Backup.created_at)).limit(50)
        )
        backups = result.scalars().all()

        return templates.TemplateResponse(
            "backups.html",
            {
                "request": request,
                "admin": admin,
                "backups": backups,
            },
        )


@app.post("/admin/backups/create")
async def create_backup(
    request: Request,
    admin: AdminUser = Depends(require_admin),
):
    """Create database backup."""
    async with db.session() as session:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"backup_{timestamp}.sql"
        backup_dir = "data/backups"
        os.makedirs(backup_dir, exist_ok=True)
        filepath = os.path.join(backup_dir, filename)

        backup_record = Backup(
            filename=filename,
            backup_type="full",
            admin_id=admin.id,
            status="completed",
        )

        try:
            # For PostgreSQL, use pg_dump
            db_url = settings.database_url
            if "postgresql" in db_url:
                # Check if pg_dump is available
                pg_dump_path = shutil.which("pg_dump")
                if not pg_dump_path:
                    raise Exception(
                        "pg_dump command not found. Please install PostgreSQL client tools. "
                        "On Ubuntu/Debian: apt-get install postgresql-client. "
                        "On macOS: brew install postgresql. "
                        "On Windows: install PostgreSQL and add bin folder to PATH."
                    )

                # Parse connection string
                import urllib.parse
                parsed = urllib.parse.urlparse(db_url.replace("postgresql+asyncpg://", "postgresql://"))

                env = os.environ.copy()
                env["PGPASSWORD"] = parsed.password or ""

                cmd = [
                    pg_dump_path,
                    "-h", parsed.hostname or "localhost",
                    "-p", str(parsed.port or 5432),
                    "-U", parsed.username or "postgres",
                    "-d", parsed.path.lstrip("/"),
                    "-f", filepath,
                ]

                result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
                if result.returncode != 0:
                    raise Exception(result.stderr or f"pg_dump failed with exit code {result.returncode}")

                backup_record.file_size = os.path.getsize(filepath)
            else:
                backup_record.status = "failed"
                backup_record.error_message = "Only PostgreSQL backups are supported"

        except subprocess.TimeoutExpired:
            backup_record.status = "failed"
            backup_record.error_message = "Backup timed out after 5 minutes"
        except Exception as e:
            backup_record.status = "failed"
            backup_record.error_message = str(e)[:500]

        session.add(backup_record)

        await log_admin_action(
            session,
            admin_id=admin.id,
            action="backup_create",
            target_type="backup",
            target_id=filename,
            details={"status": backup_record.status},
            ip_address=request.client.host,
        )

    return RedirectResponse("/admin/backups", status_code=status.HTTP_303_SEE_OTHER)


# ============= API Endpoints for CRM/BI Integration =============


@app.get("/api/v1/stats")
async def api_stats(api_key: str = Query(...)):
    """API endpoint for getting statistics."""
    expected_key = os.getenv("ADMIN_API_KEY", SECRET_KEY)
    if api_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

    async with db.session() as session:
        now = datetime.now(timezone.utc)
        thirty_days_ago = now - timedelta(days=30)

        total_users = await session.scalar(select(func.count(User.id)))
        active_users = await session.scalar(
            select(func.count(User.id)).where(User.last_seen_at >= thirty_days_ago)
        )
        total_revenue = await session.scalar(
            select(func.sum(Transaction.amount)).where(
                Transaction.status == TransactionStatus.succeeded,
                Transaction.kind == TransactionKind.purchase,
            )
        ) or 0
        total_generations = await session.scalar(select(func.count(Generation.id)))

        return JSONResponse({
            "total_users": total_users,
            "active_users": active_users,
            "total_revenue": float(total_revenue),
            "total_generations": total_generations,
            "timestamp": now.isoformat(),
        })


@app.get("/api/v1/users")
async def api_users(
    api_key: str = Query(...),
    limit: int = Query(100, le=1000),
    offset: int = Query(0),
):
    """API endpoint for getting users."""
    expected_key = os.getenv("ADMIN_API_KEY", SECRET_KEY)
    if api_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

    async with db.session() as session:
        result = await session.execute(
            select(User).order_by(desc(User.created_at)).offset(offset).limit(limit)
        )
        users = result.scalars().all()

        return JSONResponse({
            "users": [
                {
                    "id": u.id,
                    "telegram_id": u.user_id,
                    "username": u.tg_username,
                    "credits": u.credits_balance,
                    "is_premium": u.is_premium,
                    "is_frozen": u.is_frozen,
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                    "last_seen": u.last_seen_at.isoformat() if u.last_seen_at else None,
                }
                for u in users
            ],
            "limit": limit,
            "offset": offset,
        })


@app.get("/api/v1/transactions")
async def api_transactions(
    api_key: str = Query(...),
    limit: int = Query(100, le=1000),
    offset: int = Query(0),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
):
    """API endpoint for getting transactions."""
    expected_key = os.getenv("ADMIN_API_KEY", SECRET_KEY)
    if api_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

    async with db.session() as session:
        query = select(Transaction).order_by(desc(Transaction.created_at))

        if date_from:
            query = query.where(Transaction.created_at >= datetime.fromisoformat(date_from))
        if date_to:
            query = query.where(Transaction.created_at <= datetime.fromisoformat(date_to + "T23:59:59"))

        result = await session.execute(query.offset(offset).limit(limit))
        transactions = result.scalars().all()

        return JSONResponse({
            "transactions": [
                {
                    "id": tx.id,
                    "user_id": tx.user_id,
                    "amount": float(tx.amount),
                    "currency": tx.currency,
                    "status": tx.status.value,
                    "kind": tx.kind.value,
                    "provider": tx.provider,
                    "is_suspicious": tx.is_suspicious,
                    "created_at": tx.created_at.isoformat() if tx.created_at else None,
                }
                for tx in transactions
            ],
            "limit": limit,
            "offset": offset,
        })


@app.get("/api/v1/generations")
async def api_generations(
    api_key: str = Query(...),
    limit: int = Query(100, le=1000),
    offset: int = Query(0),
):
    """API endpoint for getting generations."""
    expected_key = os.getenv("ADMIN_API_KEY", SECRET_KEY)
    if api_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

    async with db.session() as session:
        result = await session.execute(
            select(Generation).order_by(desc(Generation.created_at)).offset(offset).limit(limit)
        )
        generations = result.scalars().all()

        return JSONResponse({
            "generations": [
                {
                    "id": g.id,
                    "user_id": g.user_id,
                    "status": g.status.value,
                    "credits_spent": g.credits_spent,
                    "images_generated": g.images_generated,
                    "model": g.model_name,
                    "created_at": g.created_at.isoformat() if g.created_at else None,
                    "finished_at": g.finished_at.isoformat() if g.finished_at else None,
                }
                for g in generations
            ],
            "limit": limit,
            "offset": offset,
        })


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("ADMIN_PORT", "8001"))
    uvicorn.run("admin_panel:app", host="0.0.0.0", port=port, reload=True)