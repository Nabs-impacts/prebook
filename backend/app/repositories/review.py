from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ebook import Ebook
from app.models.review import Review

REVIEW_FILTERS = ("pending", "approved", "all")


@dataclass(frozen=True, slots=True)
class AdminReviewRow:
    review: Review
    ebook_title: str


class ReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_approved(
        self,
        ebook_id: UUID,
        offset: int,
        limit: int,
    ) -> list[Review]:
        statement = (
            select(Review)
            .where(
                Review.ebook_id == ebook_id,
                Review.is_approved.is_(True),
            )
            .order_by(Review.created_at.desc(), Review.id.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.scalars(statement)
        return list(result)

    async def count_approved(self, ebook_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(Review)
            .where(
                Review.ebook_id == ebook_id,
                Review.is_approved.is_(True),
            )
        )
        return int(await self._session.scalar(statement) or 0)

    async def count_approved_by_ebooks(self, ebook_ids: list[UUID]) -> dict[UUID, int]:
        if not ebook_ids:
            return {}
        statement = (
            select(Review.ebook_id, func.count())
            .where(
                Review.ebook_id.in_(ebook_ids),
                Review.is_approved.is_(True),
            )
            .group_by(Review.ebook_id)
        )
        rows = (await self._session.execute(statement)).all()
        return {row[0]: int(row[1]) for row in rows}

    async def average_approved(self, ebook_id: UUID) -> float | None:
        statement = select(func.avg(Review.rating)).where(
            Review.ebook_id == ebook_id,
            Review.is_approved.is_(True),
        )
        average = await self._session.scalar(statement)
        return float(average) if average is not None else None

    async def list_admin(
        self,
        status: str,
        offset: int,
        limit: int,
    ) -> list[AdminReviewRow]:
        statement = select(Review, Ebook.title).join(Ebook, Ebook.id == Review.ebook_id)
        if status == "pending":
            statement = statement.where(Review.is_approved.is_(False))
        elif status == "approved":
            statement = statement.where(Review.is_approved.is_(True))
        statement = (
            statement.order_by(Review.created_at.desc(), Review.id.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = (await self._session.execute(statement)).all()
        return [AdminReviewRow(review=row[0], ebook_title=row[1]) for row in rows]

    async def count_admin(self, status: str) -> int:
        statement = select(func.count()).select_from(Review)
        if status == "pending":
            statement = statement.where(Review.is_approved.is_(False))
        elif status == "approved":
            statement = statement.where(Review.is_approved.is_(True))
        return int(await self._session.scalar(statement) or 0)

    async def get_by_id(self, review_id: UUID) -> Review | None:
        return await self._session.get(Review, review_id)

    async def create(self, review: Review) -> Review:
        self._session.add(review)
        await self._session.flush()
        await self._session.refresh(review)
        return review

    async def delete(self, review: Review) -> None:
        await self._session.delete(review)
        await self._session.flush()

    async def commit(self) -> None:
        await self._session.commit()
