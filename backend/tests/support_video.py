from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from app.models.ebook import Ebook
from app.models.enums import VideoProviderType, VideoStatus
from app.models.video import Video
from app.services.video_provider import (
    CloudflareStreamProvider,
    DirectUpload,
    VideoMetadata,
)


class InMemoryVideoRepository:
    def __init__(
        self,
        ebook_lookup: Callable[[UUID], Ebook | None] | None = None,
    ) -> None:
        self.videos: dict[UUID, Video] = {}
        self.ebook_lookup = ebook_lookup

    async def get_by_id(self, video_id: UUID, for_update: bool = False) -> Video | None:
        return self.videos.get(video_id)

    async def get_by_provider_video_id(
        self,
        provider: VideoProviderType,
        provider_video_id: str,
    ) -> Video | None:
        for video in self.videos.values():
            if video.provider is provider and video.provider_video_id == provider_video_id:
                return video
        return None

    async def get_active_for_ebook(self, ebook_id: UUID) -> Video | None:
        ebook = self.ebook_lookup(ebook_id) if self.ebook_lookup else None
        if ebook is None or ebook.preview_video_id is None:
            return None
        return self.videos.get(ebook.preview_video_id)

    async def list_by_ebook(self, ebook_id: UUID) -> list[Video]:
        return [video for video in self.videos.values() if video.ebook_id == ebook_id]

    async def create(self, video: Video) -> Video:
        video.id = uuid4()
        video.created_at = datetime.now(UTC)
        self.videos[video.id] = video
        return video

    async def delete(self, video: Video) -> None:
        self.videos.pop(video.id, None)

    async def commit(self) -> None:
        return None


class FakeCloudflareStreamProvider(CloudflareStreamProvider):
    def __init__(self) -> None:
        super().__init__("test-account", "test-token")
        self.upload = DirectUpload(
            upload_url="https://upload.cloudflare.test/direct",
            provider_video_id="cf-video-1",
        )
        self.metadata = VideoMetadata(
            status=VideoStatus.READY,
            duration_seconds=120,
            thumbnail_url="https://cdn.cloudflare.test/thumb.jpg",
            hls_url="https://cdn.cloudflare.test/video.m3u8",
        )
        self.deleted: list[str] = []
        self.create_calls = 0
        self.fetch_calls = 0

    async def create_direct_upload(
        self,
        max_duration_seconds: int,
        max_size_bytes: int,
    ) -> DirectUpload:
        self.create_calls += 1
        return self.upload

    async def fetch_metadata(self, provider_video_id: str) -> VideoMetadata:
        self.fetch_calls += 1
        return self.metadata

    async def delete(self, provider_video_id: str) -> None:
        self.deleted.append(provider_video_id)

    def parse_webhook(self, payload: dict[str, Any]) -> VideoMetadata:
        return self._metadata(payload)
