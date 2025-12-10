from __future__ import annotations

import enum
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Index,
    Text,
    func,
    select,
    text,  # ← ДОБАВЬ ЭТО
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TransactionKind(str, enum.Enum):
    purchase = "purchase"
    refund = "refund"
    payout = "payout"
    subscription = "subscription"


class TransactionStatus(str, enum.Enum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"
    canceled = "canceled"


class GenerationStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    canceled = "canceled"


class ImageRole(str, enum.Enum):
    base = "base"        # одобренный базовый кадр
    variant = "variant"  # вариант (новый ракурс/поза/кадр)
    other = "other"      # на будущее / резерв


class User(Base):
    """
    Telegram-пользователь.

    Важно:
    - id: внутренний PK
    - user_id: Telegram user_id (BigInteger), уникальный идентификатор пользователя в Telegram
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Telegram identity
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    tg_username: Mapped[Optional[str]] = mapped_column(String(64))
    lang: Mapped[Optional[str]] = mapped_column(
        String(8)
    )  # выбранный язык интерфейса бота из списка 20

    is_premium: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Балансы
    credits_balance: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # баланс в генерациях
    money_balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0.00")
    )  # условный рублёвый баланс (если нужен)

    # Метаданные
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    subscribed_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    consent_privacy: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relations
    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
        # связь по user_id (Telegram ID), см. поле Transaction.user_id
    )

    generations: Mapped[list["Generation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_users_user_id", "user_id"),
        Index("ix_users_tg_username", "tg_username"),
    )


class Transaction(Base):
    """
    Транзакции (пополнения, списания, возвраты и т.п.).
    Привязка по Telegram user_id, как в твоем шаблоне.
    """

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(128), unique=True)

    # FK к users.user_id (Telegram ID)
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )

    kind: Mapped[TransactionKind] = mapped_column(SAEnum(TransactionKind), nullable=False)
    status: Mapped[TransactionStatus] = mapped_column(
        SAEnum(TransactionStatus),
        nullable=False,
        default=TransactionStatus.pending,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 6),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="RUB")

    provider: Mapped[Optional[str]] = mapped_column(String(64))
    title: Mapped[Optional[str]] = mapped_column(String(256))

    # Доп. данные по платёжке (response платёжки, raw-поля и т.п.)
    meta: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[Optional[User]] = relationship(back_populates="transactions")

    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_transactions_amount_non_negative"),
        Index("ix_transactions_user_id", "user_id"),
        Index("ix_transactions_external_id", "external_id"),
        Index("ix_transactions_kind_status", "kind", "status"),
    )


class Generation(Base):
    """
    Задание на генерацию (Seedream 4.0, один логический запрос пользователя).

    На уровне кода ты можешь запускать одну или несколько реальных API-генераций
    под одной записью Generation.
    """

    __tablename__ = "generations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Привязка по Telegram user_id, как у Transaction
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )

    # Идентификатор запроса на стороне Seedream (если есть)
    external_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)

    # Текст промпта (английский, собранный из UI)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)

    # Имя модели (на будущее, если будет несколько)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False, default="seedream-4.0")

    # Параметры генерации (aspect ratio, style, hair_color и т.п.) в структурированном виде
    params: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)

    # Массив исходных картинок одежды / модели
    source_image_urls: Mapped[Optional[list[str]]] = mapped_column(JSONB)

    # План/факт по количеству картинок
    total_images_planned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    images_generated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Кредиты, списанные за эту генерацию
    credits_spent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[GenerationStatus] = mapped_column(
        SAEnum(GenerationStatus),
        nullable=False,
        default=GenerationStatus.queued,
    )
    error_message: Mapped[Optional[str]] = mapped_column(String(512))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(back_populates="generations")
    images: Mapped[list["GeneratedImage"]] = relationship(
        back_populates="generation",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_generations_user_id", "user_id"),
        Index("ix_generations_status", "status"),
    )


class GeneratedImage(Base):
    """
    Конкретное сгенерированное изображение (результат Seedream).
    """

    __tablename__ = "generated_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    generation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("generations.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Дублируем user_id для удобной выборки без join'a
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )

    role: Mapped[ImageRole] = mapped_column(
        SAEnum(ImageRole), nullable=False, default=ImageRole.other
    )

    # Где физически лежит картинка (S3 / CDN / локальный путь и т.п.)
    storage_url: Mapped[Optional[str]] = mapped_column(String(1024))

    # Telegram file_id (document/photo) для повторной отправки без перезагрузки
    telegram_file_id: Mapped[Optional[str]] = mapped_column(String(256), index=True)

    width: Mapped[Optional[int]] = mapped_column(Integer)
    height: Mapped[Optional[int]] = mapped_column(Integer)

    meta: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    generation: Mapped["Generation"] = relationship(back_populates="images")
    user: Mapped["User"] = relationship()

    __table_args__ = (
        Index("ix_generated_images_generation_id", "generation_id"),
        Index("ix_generated_images_user_id", "user_id"),
        Index("ix_generated_images_role", "role"),
    )


class AdminUser(Base):
    """Admin panel users for web interface."""

    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(256), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AdminActionLog(Base):
    """Log of admin actions in the panel."""

    __tablename__ = "admin_action_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
    )

    action: Mapped[str] = mapped_column(String(128), nullable=False)  # e.g., "user_balance_update"
    target_type: Mapped[Optional[str]] = mapped_column(String(64))  # e.g., "user", "transaction"
    target_id: Mapped[Optional[str]] = mapped_column(String(128))  # ID of affected entity

    details: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)  # Additional info
    ip_address: Mapped[Optional[str]] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_admin_logs_admin_id", "admin_id"),
        Index("ix_admin_logs_created_at", "created_at"),
        Index("ix_admin_logs_action", "action"),
    )


@dataclass
class Database:
    """
    Лёгкая async-обёртка над SQLAlchemy под PostgreSQL (asyncpg).

    Usage:
        db = await Database.create("postgresql+asyncpg://user:pass@host:5432/dbname")
        async with db.session() as s:
            ...
    """

    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]

    @classmethod
    async def create(cls, url: str) -> "Database":
        """
        Создать движок/фабрику сессий и прогнать Base.metadata.create_all.

        Ориентация на PostgreSQL (postgresql+asyncpg).

        Доп. логика:
        - перед созданием схемы дропаем "старый" индекс ix_generations_external_id,
          если он вдруг уже существует (последствия предыдущих версий схемы).
        """
        if not url.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "Expected URL like postgresql+asyncpg://user:password@host:port/dbname"
            )

        engine = create_async_engine(
            url,
            echo=False,
            pool_pre_ping=True,
        )

        session_factory = async_sessionmaker(
            engine,
            expire_on_commit=False,
        )

        # Создание схемы (для продакшена обычно миграции через Alembic)
        async with engine.begin() as conn:
            # ХОТ-ФИКС: на всякий случай удаляем конфликтующий индекс,
            # чтобы не получать DuplicateTableError при create_all().
            # Если индекса нет — команда ничего не сделает.
            await conn.execute(
                text('DROP INDEX IF EXISTS "ix_generations_external_id"')
            )

            # После этого создаём все таблицы и индексы по текущей модели.
            await conn.run_sync(Base.metadata.create_all)

        return cls(engine=engine, session_factory=session_factory)


    @asynccontextmanager
    async def session(self) -> AsyncSession:
        """
        Контекстный менеджер с авто-commit/rollback.
        """
        session: AsyncSession = self.session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def close(self) -> None:
        await self.engine.dispose()


async def upsert_user_basic(
    session: AsyncSession,
    *,
    user_id: int,  # Telegram user_id
    tg_username: Optional[str] = None,
    lang: Optional[str] = None,
    is_premium: Optional[bool] = None,
    is_bot: Optional[bool] = None,
    last_seen_at: Optional[datetime] = None,
    consent_privacy: Optional[bool] = None,
) -> User:
    """
    Создать или обновить пользователя по Telegram user_id.
    """
    result = await session.execute(select(User).where(User.user_id == user_id))
    user: Optional[User] = result.scalar_one_or_none()

    if user is None:
        user = User(
            user_id=user_id,
            tg_username=tg_username,
            lang=lang,
            is_premium=bool(is_premium) if is_premium is not None else False,
            is_bot=bool(is_bot) if is_bot is not None else False,
            last_seen_at=last_seen_at,
            consent_privacy=bool(consent_privacy) if consent_privacy is not None else False,
        )
        session.add(user)
    else:
        if tg_username is not None:
            user.tg_username = tg_username
        if lang is not None:
            user.lang = lang
        if is_premium is not None:
            user.is_premium = bool(is_premium)
        if is_bot is not None:
            user.is_bot = bool(is_bot)
        if last_seen_at is not None:
            user.last_seen_at = last_seen_at
        if consent_privacy is not None:
            user.consent_privacy = bool(consent_privacy)

    return user


async def record_transaction(
    session: AsyncSession,
    *,
    user_id: Optional[int],  # Telegram user_id
    kind: TransactionKind,
    amount: Decimal | float | int,
    currency: str = "RUB",
    provider: Optional[str] = None,
    status: TransactionStatus = TransactionStatus.pending,
    title: Optional[str] = None,
    external_id: Optional[str] = None,
    meta: Optional[dict[str, Any]] = None,
) -> Transaction:
    """
    Создать транзакцию.

    Если external_id уже есть в базе — вернёт существующую строку (идемпотентность).
    """
    if external_id:
        result = await session.execute(
            select(Transaction).where(Transaction.external_id == external_id)
        )
        existing: Optional[Transaction] = result.scalar_one_or_none()
        if existing:
            return existing

    tx = Transaction(
        user_id=user_id,
        kind=kind,
        amount=Decimal(str(amount)),
        currency=currency.upper(),
        provider=provider,
        status=status,
        title=title,
        external_id=external_id,
        meta=meta,
    )
    session.add(tx)
    return tx


async def create_generation(
    session: AsyncSession,
    *,
    user_id: int,  # Telegram user_id
    prompt: str,
    model_name: str = "seedream-4.0",
    params: Optional[dict[str, Any]] = None,
    source_image_urls: Optional[list[str]] = None,
    total_images_planned: int = 0,
    credits_spent: int = 0,
    status: GenerationStatus = GenerationStatus.queued,
    external_id: Optional[str] = None,
) -> Generation:
    """
    Создать запись Generation перед вызовом Seedream API.
    """
    generation = Generation(
        user_id=user_id,
        prompt=prompt,
        model_name=model_name,
        params=params,
        source_image_urls=source_image_urls,
        total_images_planned=total_images_planned,
        images_generated=0,
        credits_spent=credits_spent,
        status=status,
        external_id=external_id,
    )
    session.add(generation)
    return generation