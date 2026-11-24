from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import VideoProviderType, VideoStatus


class VideoUploadTicket(BaseModel):
    video_id: UUID
    provider_video_id: str
    upload_url: str


class ExternalVideoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    url: str = Field(min_length=1, max_length=1024)

    @field_validator("url")
    @classmethod
    def strip_url(cls, value: str) -> str:
        return value.strip()


class VideoRead(BaseModel):
    id: UUID
    ebook_id: UUID
    provider: VideoProviderType
    provider_video_id: str | None
    external_url: str | None
    status: VideoStatus
    duration_seconds: int | None
    thumbnail_url: str | None
    hls_url: str | None
    embed_url: str | None
    created_at: datetime


class EbookVideo(BaseModel):
    provider: VideoProviderType
    hls_url: str | None
    thumbnail_url: str | None
    duration_seconds: int | None
    embed_url: str | None
