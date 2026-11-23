from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ebook import Ebook
from app.models.review import Review


@dataclass(frozen=True, slots=True)
class EbookListRow:
    id: UUID
    title: str
    slug: str
    price: int
    cover_url: str
    summary: str


class EbookRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, ebook_id: UUID, for_update: bool = False) -> Ebook | None:
        statement = select(Ebook).where(
            Ebook.id == ebook_id,
            Ebook.deleted_at.is_(None),
        )
        if for_update:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    async def get_by_slug(self, slug: str, published_only: bool = False) -> Ebook | None:
        statement = select(Ebook).where(
            Ebook.slug == slug,
            Ebook.deleted_at.is_(None),
        )
        if published_only:
            statement = statement.where(Ebook.is_published.is_(True))
        return await self._session.scalar(statement)

    async def get_detail_by_slug(self, slug: str) -> tuple[Ebook, float | None] | None:
        average_rating = (
            select(func.avg(Review.rating))
            .where(
                Review.ebook_id == Ebook.id,
                Review.is_approved.is_(True),
            )
            .scalar_subquery()
        )
        statement = select(Ebook, average_rating.label("average_rating")).where(
            Ebook.slug == slug,
            Ebook.is_published.is_(True),
            Ebook.deleted_at.is_(None),
        )
        row = (await self._session.execute(statement)).first()
        if row is None:
            return None
        ebook = row[0]
        average = row[1]
        return ebook, float(average) if average is not None else None

    async def list_published(self, offset: int, limit: int) -> list[EbookListRow]:
        statement = (
            select(
                Ebook.id,
                Ebook.title,
                Ebook.slug,
                Ebook.price,
                Ebook.cover_url,
                Ebook.summary,
            )
            .where(
                Ebook.is_published.is_(True),
                Ebook.deleted_at.is_(None),
            )
            .order_by(Ebook.created_at.desc(), Ebook.id.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = (await self._session.execute(statement)).all()
        return [
            EbookListRow(
                id=row.id,
                title=row.title,
                slug=row.slug,
                price=row.price,
                cover_url=row.cover_url,
                summary=row.summary,
            )
            for row in rows
        ]

    async def count_published(self) -> int:
        statement = (
            select(func.count())
            .select_from(Ebook)
            .where(
                Ebook.is_published.is_(True),
                Ebook.deleted_at.is_(None),
            )
        )
        return int(await self._session.scalar(statement) or 0)

    async def list_admin(self, offset: int, limit: int) -> list[Ebook]:
        statement = (
            select(Ebook)
            .where(Ebook.deleted_at.is_(None))
            .order_by(Ebook.created_at.desc(), Ebook.id.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.scalars(statement)
        return list(result)

    async def count_admin(self) -> int:
        statement = select(func.count()).select_from(Ebook).where(Ebook.deleted_at.is_(None))
        return int(await self._session.scalar(statement) or 0)

    async def slug_exists(self, slug: str) -> bool:
        statement = select(Ebook.id).where(Ebook.slug == slug).limit(1)
        return await self._session.scalar(statement) is not None

    async def create(self, ebook: Ebook) -> Ebook:
        self._session.add(ebook)
        await self._session.flush()
        await self._session.refresh(ebook)
        return ebook

    async def delete(self, ebook: Ebook) -> None:
        await self._session.delete(ebook)
        await self._session.flush()

    async def commit(self) -> None:
        await self._session.commit()
