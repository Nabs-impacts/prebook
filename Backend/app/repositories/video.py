from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ebook import Ebook
from app.models.enums import VideoProviderType
from app.models.video import Video


class VideoRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, video_id: UUID, for_update: bool = False) -> Video | None:
        statement = select(Video).where(Video.id == video_id)
        if for_update:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    async def get_by_provider_video_id(
        self,
        provider: VideoProviderType,
        provider_video_id: str,
    ) -> Video | None:
        statement = select(Video).where(
            Video.provider == provider,
            Video.provider_video_id == provider_video_id,
        )
        return await self._session.scalar(statement)

    async def get_active_for_ebook(self, ebook_id: UUID) -> Video | None:
        statement = (
            select(Video)
            .join(Ebook, Ebook.preview_video_id == Video.id)
            .where(Ebook.id == ebook_id)
        )
        return await self._session.scalar(statement)

    async def list_by_ebook(self, ebook_id: UUID) -> list[Video]:
        statement = select(Video).where(Video.ebook_id == ebook_id)
        result = await self._session.scalars(statement)
        return list(result)

    async def create(self, video: Video) -> Video:
        self._session.add(video)
        await self._session.flush()
        await self._session.refresh(video)
        return video

    async def delete(self, video: Video) -> None:
        await self._session.delete(video)
        await self._session.flush()

    async def commit(self) -> None:
        await self._session.commit()
