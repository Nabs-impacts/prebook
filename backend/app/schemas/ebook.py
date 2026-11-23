from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.text import sanitize_text

MAX_SUMMARY_LENGTH = 500
MAX_DESCRIPTION_LENGTH = 50000
MAX_REVIEW_COMMENT_LENGTH = 2000


class EbookCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION_LENGTH)
    summary: str | None = Field(default=None, max_length=MAX_SUMMARY_LENGTH)
    price: int = Field(ge=0)
    preview_video_id: str | None = Field(default=None, max_length=255)

    @field_validator("title", "description", "summary", "preview_video_id")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class EbookUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_DESCRIPTION_LENGTH,
    )
    summary: str | None = Field(default=None, max_length=MAX_SUMMARY_LENGTH)
    price: int | None = Field(default=None, ge=0)
    preview_video_id: str | None = Field(default=None, max_length=255)
    is_published: bool | None = None

    @field_validator("title", "description", "summary", "preview_video_id")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @model_validator(mode="after")
    def check_update(self) -> "EbookUpdate":
        if not self.model_fields_set:
            raise ValueError("Aucune modification fournie.")
        return self


class EbookListItem(BaseModel):
    id: UUID
    title: str
    slug: str
    price: int
    cover_url: str
    summary: str
    reviews_count: int | None = None
    purchases_count: int | None = None


class EbookListResponse(BaseModel):
    items: list[EbookListItem]
    total: int
    page: int
    page_size: int
    pages: int


class EbookDetail(BaseModel):
    id: UUID
    title: str
    slug: str
    description: str
    summary: str
    price: int
    cover_url: str
    preview_video_id: str | None
    average_rating: float | None
    reviews_count: int | None = None
    purchases_count: int | None = None


class AdminEbookRead(BaseModel):
    id: UUID
    title: str
    slug: str
    description: str
    summary: str
    price: int
    cover_url: str
    has_pdf: bool
    preview_video_id: str | None
    is_published: bool
    deleted_at: datetime | None
    created_at: datetime


class AdminEbookListResponse(BaseModel):
    items: list[AdminEbookRead]
    total: int
    page: int
    page_size: int
    pages: int


class ReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    author_name: str = Field(min_length=1, max_length=255)
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=MAX_REVIEW_COMMENT_LENGTH)

    @field_validator("author_name")
    @classmethod
    def clean_author_name(cls, value: str) -> str:
        cleaned = sanitize_text(value, 255, collapse_whitespace=True)
        if not cleaned:
            raise ValueError("Le nom est requis.")
        return cleaned

    @field_validator("comment")
    @classmethod
    def clean_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = sanitize_text(value, MAX_REVIEW_COMMENT_LENGTH)
        return cleaned or None


class ReviewRead(BaseModel):
    id: UUID
    author_name: str
    rating: int
    comment: str | None
    created_at: datetime


class ReviewListResponse(BaseModel):
    items: list[ReviewRead]
    total: int
    page: int
    page_size: int
    pages: int


class AdminReviewRead(ReviewRead):
    ebook_id: UUID
    ebook_title: str
    is_approved: bool


class AdminReviewListResponse(BaseModel):
    items: list[AdminReviewRead]
    total: int
    page: int
    page_size: int
    pages: int
