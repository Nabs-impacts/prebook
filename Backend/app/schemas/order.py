from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import OrderStatus


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    ebook_slug: str = Field(min_length=1, max_length=255)
    buyer_name: str = Field(min_length=1, max_length=255)
    buyer_email: EmailStr
    payment_method: str | None = Field(default=None, max_length=50)

    @field_validator("ebook_slug", "buyer_name")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class OrderCreateResponse(BaseModel):
    public_id: UUID
    status: OrderStatus
    amount: int
    currency: str
    provider: str
    payment_url: str | None
    payment_expires_at: datetime | None
    created_at: datetime


class OrderStatusResponse(BaseModel):
    public_id: UUID
    status: OrderStatus
    amount: int
    currency: str
    payment_url: str | None
    payment_expires_at: datetime | None
    created_at: datetime
    paid_at: datetime | None


class AdminOrderRead(BaseModel):
    id: UUID
    buyer_name: str
    buyer_email: str
    ebook_id: UUID
    ebook_title: str
    ebook_slug: str
    amount: int
    currency: str
    status: OrderStatus
    provider: str
    provider_reference: str | None
    payment_url: str | None
    payment_expires_at: datetime | None
    payment_failure_reason: str | None
    paid_at: datetime | None
    created_at: datetime


class AdminOrderListResponse(BaseModel):
    items: list[AdminOrderRead]
    total: int
    page: int
    page_size: int
    pages: int
