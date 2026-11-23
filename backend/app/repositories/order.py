from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OrderStatus
from app.models.order import Order


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
