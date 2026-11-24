from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ebook import Ebook
from app.models.enums import OrderStatus
from app.models.order import Order


@dataclass(frozen=True, slots=True)
class OrderAdminFilters:
    status: OrderStatus | None = None
    ebook_id: UUID | None = None
    ebook_slug: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    payment_method: str | None = None
    email: str | None = None


@dataclass(frozen=True, slots=True)
class OrderAdminRow:
    order: Order
    ebook_title: str
    ebook_slug: str


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def count_paid_by_ebook(self, ebook_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(Order)
            .where(
                Order.ebook_id == ebook_id,
                Order.status == OrderStatus.PAID,
            )
        )
        return int(await self._session.scalar(statement) or 0)

    async def count_paid_by_ebooks(self, ebook_ids: list[UUID]) -> dict[UUID, int]:
        if not ebook_ids:
            return {}
        statement = (
            select(Order.ebook_id, func.count())
            .where(
                Order.ebook_id.in_(ebook_ids),
                Order.status == OrderStatus.PAID,
            )
            .group_by(Order.ebook_id)
        )
        rows = (await self._session.execute(statement)).all()
        return {row[0]: int(row[1]) for row in rows}

    async def exists_for_ebook(self, ebook_id: UUID) -> bool:
        statement = select(Order.id).where(Order.ebook_id == ebook_id).limit(1)
        return await self._session.scalar(statement) is not None

    async def get_by_id(self, order_id: UUID, for_update: bool = False) -> Order | None:
        statement = select(Order).where(Order.id == order_id)
        if for_update:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    async def get_by_idempotency_key(self, idempotency_key: str) -> Order | None:
        statement = select(Order).where(Order.idempotency_key == idempotency_key)
        return await self._session.scalar(statement)

    async def get_by_provider_reference(
        self,
        provider: str,
        provider_reference: str,
        for_update: bool = False,
    ) -> Order | None:
        statement = select(Order).where(
            Order.provider == provider,
            Order.provider_reference == provider_reference,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    async def list_pending_before(self, cutoff: datetime, limit: int) -> list[Order]:
        statement = (
            select(Order)
            .where(
                Order.status == OrderStatus.PENDING,
                Order.created_at <= cutoff,
            )
            .order_by(Order.created_at.asc())
            .limit(limit)
        )
        result = await self._session.scalars(statement)
        return list(result)

    async def list_admin(
        self,
        filters: OrderAdminFilters,
        offset: int,
        limit: int,
    ) -> list[OrderAdminRow]:
        statement = (
            select(Order, Ebook.title, Ebook.slug)
            .join(Ebook, Order.ebook_id == Ebook.id)
            .where(*self._conditions(filters))
            .order_by(Order.created_at.desc(), Order.id.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = (await self._session.execute(statement)).all()
        return [OrderAdminRow(order=row[0], ebook_title=row[1], ebook_slug=row[2]) for row in rows]

    async def count_admin(self, filters: OrderAdminFilters) -> int:
        statement = (
            select(func.count())
            .select_from(Order)
            .join(Ebook, Order.ebook_id == Ebook.id)
            .where(*self._conditions(filters))
        )
        return int(await self._session.scalar(statement) or 0)

    async def get_admin_detail(self, order_id: UUID) -> OrderAdminRow | None:
        statement = (
            select(Order, Ebook.title, Ebook.slug)
            .join(Ebook, Order.ebook_id == Ebook.id)
            .where(Order.id == order_id)
        )
        row = (await self._session.execute(statement)).first()
        if row is None:
            return None
        return OrderAdminRow(order=row[0], ebook_title=row[1], ebook_slug=row[2])

    async def create(self, order: Order) -> Order:
        self._session.add(order)
        await self._session.flush()
        await self._session.refresh(order)
        return order

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()

    def _conditions(self, filters: OrderAdminFilters) -> list[Any]:
        conditions: list[Any] = []
        if filters.status is not None:
            conditions.append(Order.status == filters.status)
        if filters.ebook_id is not None:
            conditions.append(Order.ebook_id == filters.ebook_id)
        if filters.ebook_slug is not None:
            conditions.append(Ebook.slug == filters.ebook_slug)
        if filters.date_from is not None:
            conditions.append(Order.created_at >= filters.date_from)
        if filters.date_to is not None:
            conditions.append(Order.created_at <= filters.date_to)
        if filters.payment_method is not None:
            conditions.append(Order.payment_method == filters.payment_method)
        if filters.email:
            conditions.append(
                func.lower(Order.buyer_email).like(f"%{filters.email.strip().lower()}%")
            )
        return conditions
