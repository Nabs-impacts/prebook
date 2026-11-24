import hashlib
import hmac
import json
from typing import Any
from uuid import UUID

from app.core.errors import BadRequestError, NotFoundError
from app.models.enums import VideoProviderType, VideoStatus
from app.models.video import Video
from app.repositories.catalog_cache import CatalogCacheRepository
from app.repositories.ebook import EbookRepository
from app.repositories.video import VideoRepository
from app.schemas.video import EbookVideo, VideoRead, VideoUploadTicket
from app.services.video_provider import (
    CloudflareStreamProvider,
    ExternalUrlProvider,
    VideoMetadata,
    cloudflare_embed_url,
)


def video_embed_url(video: Video) -> str | None:
    if video.provider is VideoProviderType.EXTERNAL_URL and video.external_url:
        try:
            return ExternalUrlProvider().embed_url(video.external_url)
        except BadRequestError:
            return None
    if video.provider is VideoProviderType.CLOUDFLARE_STREAM and video.provider_video_id:
        return cloudflare_embed_url(video.provider_video_id)
    return None


def build_public_video(video: Video | None) -> EbookVideo | None:
    if video is None or video.status is not VideoStatus.READY:
        return None
    return EbookVideo(
        provider=video.provider,
        hls_url=video.hls_url,
        thumbnail_url=video.thumbnail_url,
        duration_seconds=video.duration_seconds,
        embed_url=video_embed_url(video),
    )


class VideoService:
    def __init__(
        self,
        video_repository: VideoRepository,
        ebook_repository: EbookRepository,
        cache_repository: CatalogCacheRepository,
        cloudflare_provider: CloudflareStreamProvider,
        external_provider: ExternalUrlProvider,
        *,
        max_duration_seconds: int,
        max_size_bytes: int,
        webhook_secret: str | None,
    ) -> None:
        self._video_repository = video_repository
        self._ebook_repository = ebook_repository
        self._cache_repository = cache_repository
        self._cloudflare_provider = cloudflare_provider
        self._external_provider = external_provider
        self._max_duration_seconds = max_duration_seconds
        self._max_size_bytes = max_size_bytes
        self._webhook_secret = webhook_secret

    async def create_upload(self, ebook_id: UUID) -> VideoUploadTicket:
        ebook = await self._ebook_repository.get_by_id(ebook_id)
        if ebook is None:
            raise NotFoundError("Ebook introuvable.")
        upload = await self._cloudflare_provider.create_direct_upload(
            self._max_duration_seconds,
            self._max_size_bytes,
        )
        video = Video(
            ebook_id=ebook.id,
            provider=VideoProviderType.CLOUDFLARE_STREAM,
            provider_video_id=upload.provider_video_id,
            status=VideoStatus.UPLOADING,
        )
        created = await self._video_repository.create(video)
        await self._video_repository.commit()
        return VideoUploadTicket(
            video_id=created.id,
            provider_video_id=upload.provider_video_id,
            upload_url=upload.upload_url,
        )

    async def attach_external(self, ebook_id: UUID, url: str) -> VideoRead:
        parsed = self._external_provider.parse(url)
        ebook = await self._ebook_repository.get_by_id(ebook_id, for_update=True)
        if ebook is None:
            raise NotFoundError("Ebook introuvable.")
        previous_id = ebook.preview_video_id
        video = Video(
            ebook_id=ebook.id,
            provider=VideoProviderType.EXTERNAL_URL,
            provider_video_id=parsed.provider_video_id,
            external_url=url.strip(),
            status=VideoStatus.READY,
        )
        created = await self._video_repository.create(video)
        ebook.preview_video_id = created.id
        await self._video_repository.commit()
        if previous_id is not None and previous_id != created.id:
            await self._delete_video_by_id(previous_id)
        await self._cache_repository.bump_version()
        return self._video_read(created)

    async def refresh(self, video_id: UUID) -> VideoRead:
        video = await self._video_repository.get_by_id(video_id)
        if video is None:
            raise NotFoundError("Vidéo introuvable.")
        if video.provider is not VideoProviderType.CLOUDFLARE_STREAM or not video.provider_video_id:
            return self._video_read(video)
        metadata = await self._cloudflare_provider.fetch_metadata(video.provider_video_id)
        await self._apply_metadata(video, metadata)
        return self._video_read(video)

    async def detach(self, ebook_id: UUID) -> None:
        ebook = await self._ebook_repository.get_by_id(ebook_id, for_update=True)
        if ebook is None:
            raise NotFoundError("Ebook introuvable.")
        videos = await self._video_repository.list_by_ebook(ebook_id)
        ebook.preview_video_id = None
        for video in videos:
            await self._delete_remote(video)
        for video in videos:
            await self._video_repository.delete(video)
        await self._video_repository.commit()
        await self._cache_repository.bump_version()

    def verify_webhook_signature(self, header: str | None, body: bytes) -> bool:
        if not self._webhook_secret or not header:
            return False
        values: dict[str, str] = {}
        for part in header.split(","):
            key, separator, value = part.partition("=")
            if not separator:
                return False
            values[key.strip()] = value.strip()
        timestamp = values.get("time")
        signature = values.get("sig1")
        if not timestamp or not signature:
            return False
        message = f"{timestamp}.".encode() + body
        expected = hmac.new(
            self._webhook_secret.encode(),
            message,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    async def handle_webhook(self, body: bytes) -> None:
        payload = self._decode_payload(body)
        video_id = payload.get("uid")
        if not isinstance(video_id, str) or not video_id:
            raise BadRequestError("Charge utile de webhook invalide.")
        video = await self._video_repository.get_by_provider_video_id(
            VideoProviderType.CLOUDFLARE_STREAM,
            video_id,
        )
        if video is None:
            return
        metadata = self._cloudflare_provider.parse_webhook(payload)
        await self._apply_metadata(video, metadata)

    async def _apply_metadata(self, video: Video, metadata: VideoMetadata) -> None:
        video.status = metadata.status
        video.duration_seconds = metadata.duration_seconds
        video.thumbnail_url = metadata.thumbnail_url
        video.hls_url = metadata.hls_url
        await self._video_repository.commit()
        if metadata.status is VideoStatus.READY:
            await self._activate(video)
        await self._cache_repository.bump_version()

    async def _activate(self, video: Video) -> None:
        ebook = await self._ebook_repository.get_by_id(video.ebook_id, for_update=True)
        if ebook is None or ebook.preview_video_id == video.id:
            return
        previous_id = ebook.preview_video_id
        ebook.preview_video_id = video.id
        await self._ebook_repository.commit()
        if previous_id is not None:
            await self._delete_video_by_id(previous_id)

    async def _delete_video_by_id(self, video_id: UUID) -> None:
        video = await self._video_repository.get_by_id(video_id)
        if video is None:
            return
        await self._delete_remote(video)
        await self._video_repository.delete(video)
        await self._video_repository.commit()

    async def _delete_remote(self, video: Video) -> None:
        if video.provider is VideoProviderType.CLOUDFLARE_STREAM and video.provider_video_id:
            await self._cloudflare_provider.delete(video.provider_video_id)

    def _decode_payload(self, body: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BadRequestError("Charge utile de webhook invalide.") from error
        if not isinstance(payload, dict):
            raise BadRequestError("Charge utile de webhook invalide.")
        return payload

    def _video_read(self, video: Video) -> VideoRead:
        return VideoRead(
            id=video.id,
            ebook_id=video.ebook_id,
            provider=video.provider,
            provider_video_id=video.provider_video_id,
            external_url=video.external_url,
            status=video.status,
            duration_seconds=video.duration_seconds,
            thumbnail_url=video.thumbnail_url,
            hls_url=video.hls_url,
            embed_url=video_embed_url(video),
            created_at=video.created_at,
        )
