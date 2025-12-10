"""
Web Admin Panel for Seedream Bot
FastAPI-based admin interface with user management, analytics, and financial controls
"""

import os
import secrets
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional, List, Dict, Any
import csv
import io

from fastapi import FastAPI, Request, Depends, HTTPException, status, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
import passlib.hash

from sqlalchemy import select, func, and_, or_, desc
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
)
from config import load_env

# Initialize FastAPI app
app = FastAPI(title="Seedream Admin Panel", version="1.0.0")

# Load environment
settings = load_env()

# Session middleware for authentication
SECRET_KEY = os.getenv("ADMIN_SECRET_KEY", secrets.token_urlsafe(32))
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# Templates and static files
templates = Jinja2Templates(directory="admin/templates")
app.mount("/static", StaticFiles(directory="admin/static"), name="static")

# Database
db: Optional[Database] = None


@app.on_event("startup")
async def startup():
    """Initialize database on startup."""
    global db
    db = await Database.create(settings.database_url)


@app.on_event("shutdown")
async def shutdown():
    """Close database on shutdown."""
    if db:
        await db.close()


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
    return passlib.hash.bcrypt.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    """Hash password."""
    return passlib.hash.bcrypt.hash(password)


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


# ============= Routes =============


@app.get("/admin/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Show login page."""
    # If already logged in, redirect to dashboard
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

        # Update last login
        admin.last_login = datetime.now(timezone.utc)
        await session.commit()

        # Set session
        request.session["admin_id"] = admin.id

        return RedirectResponse("/admin/", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/admin/logout")
async def logout(request: Request):
    """Logout admin user."""
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/admin/", response_class=HTMLResponse)
async def dashboard(request: Request, admin: AdminUser = Depends(require_admin)):
    """Main dashboard with analytics."""
    async with db.session() as session:
        # Calculate metrics
        total_users = await session.scalar(select(func.count(User.id)))

        # Active users (last 30 days)
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        active_users = await session.scalar(
            select(func.count(User.id)).where(User.last_seen_at >= thirty_days_ago)
        )

        # Total revenue
        total_revenue = await session.scalar(
            select(func.sum(Transaction.amount)).where(
                Transaction.status == TransactionStatus.succeeded,
                Transaction.kind == TransactionKind.purchase,
            )
        ) or Decimal(0)

        # Total generations
        total_generations = await session.scalar(select(func.count(Generation.id)))

        # Successful generations
        successful_generations = await session.scalar(
            select(func.count(Generation.id)).where(Generation.status == GenerationStatus.succeeded)
        )

        # Average check
        avg_check = await session.scalar(
            select(func.avg(Transaction.amount)).where(
                Transaction.status == TransactionStatus.succeeded,
                Transaction.kind == TransactionKind.purchase,
            )
        ) or Decimal(0)

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

        stats = {
            "total_users": total_users,
            "active_users": active_users,
            "total_revenue": float(total_revenue),
            "total_generations": total_generations,
            "successful_generations": successful_generations,
            "success_rate": (
                round(successful_generations / total_generations * 100, 2)
                if total_generations > 0
                else 0
            ),
            "avg_check": float(avg_check),
        }

        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "admin": admin,
                "stats": stats,
                "recent_transactions": recent_transactions,
                "recent_users": recent_users,
            },
        )


@app.get("/admin/users", response_class=HTMLResponse)
async def users_list(
    request: Request,
    admin: AdminUser = Depends(require_admin),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
):
    """List users with search and pagination."""
    async with db.session() as session:
        ITEMS_PER_PAGE = 50

        # Build query
        query = select(User)

        # Search filter
        if search:
            search_filter = or_(
                User.user_id == int(search) if search.isdigit() else False,
                User.tg_username.ilike(f"%{search}%"),
            )
            query = query.where(search_filter)

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
        # Get user
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

        return templates.TemplateResponse(
            "user_detail.html",
            {
                "request": request,
                "admin": admin,
                "user": user,
                "transactions": transactions,
                "generations": generations,
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

        # Update balance
        user.credits_balance = (user.credits_balance or 0) + amount

        # Log action
        await log_admin_action(
            session,
            admin_id=admin.id,
            action="user_balance_adjust",
            target_type="user",
            target_id=str(user.user_id),
            details={"amount": amount, "reason": reason, "new_balance": user.credits_balance},
            ip_address=request.client.host,
        )

        await session.commit()

    return RedirectResponse(
        f"/admin/users/{user_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/admin/transactions", response_class=HTMLResponse)
async def transactions_list(
    request: Request,
    admin: AdminUser = Depends(require_admin),
    user_id: Optional[int] = Query(None),
    status_filter: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
):
    """List transactions with filters."""
    async with db.session() as session:
        ITEMS_PER_PAGE = 50

        # Build query
        query = select(Transaction)

        # Filters
        filters = []
        if user_id:
            filters.append(Transaction.user_id == user_id)
        if status_filter:
            filters.append(Transaction.status == status_filter)

        if filters:
            query = query.where(and_(*filters))

        # Count total
        count_query = select(func.count()).select_from(query.subquery())
        total_transactions = await session.scalar(count_query)

        # Paginate
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
                "page": page,
                "total_pages": total_pages,
                "total_transactions": total_transactions,
            },
        )


@app.get("/admin/export/users")
async def export_users(admin: AdminUser = Depends(require_admin)):
    """Export users to CSV."""
    async with db.session() as session:
        result = await session.execute(select(User).order_by(User.created_at))
        users = result.scalars().all()

        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow(
            ["ID", "Telegram ID", "Username", "Credits", "Created At", "Last Seen"]
        )

        # Data
        for user in users:
            writer.writerow([
                user.id,
                user.user_id,
                user.tg_username or "",
                user.credits_balance or 0,
                user.created_at.isoformat() if user.created_at else "",
                user.last_seen_at.isoformat() if user.last_seen_at else "",
            ])

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=users.csv"},
        )


@app.get("/admin/export/transactions")
async def export_transactions(admin: AdminUser = Depends(require_admin)):
    """Export transactions to CSV."""
    async with db.session() as session:
        result = await session.execute(select(Transaction).order_by(Transaction.created_at))
        transactions = result.scalars().all()

        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow([
            "ID",
            "User ID",
            "Amount",
            "Currency",
            "Status",
            "Kind",
            "Provider",
            "Created At",
        ])

        # Data
        for tx in transactions:
            writer.writerow([
                tx.id,
                tx.user_id or "",
                float(tx.amount),
                tx.currency,
                tx.status.value,
                tx.kind.value,
                tx.provider or "",
                tx.created_at.isoformat() if tx.created_at else "",
            ])

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=transactions.csv"},
        )


@app.get("/admin/logs", response_class=HTMLResponse)
async def admin_logs(
    request: Request,
    admin: AdminUser = Depends(require_admin),
    page: int = Query(1, ge=1),
):
    """View admin action logs."""
    async with db.session() as session:
        ITEMS_PER_PAGE = 50

        # Count total
        total_logs = await session.scalar(select(func.count(AdminActionLog.id)))

        # Get logs
        offset = (page - 1) * ITEMS_PER_PAGE
        result = await session.execute(
            select(AdminActionLog)
            .order_by(desc(AdminActionLog.created_at))
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
                "page": page,
                "total_pages": total_pages,
            },
        )


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("ADMIN_PORT", "8001"))
    uvicorn.run("admin_panel:app", host="0.0.0.0", port=port, reload=True)
