from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import OrderStatus


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    ebook_slug: str = Field(min_length=1, max_length=255)
    buyer_name: str = Field(min_length=1, max_length=255)
    buyer_email: EmailStr
    payment_method: str = Field(min_length=1, max_length=50)

    @field_validator("ebook_slug", "buyer_name")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("payment_method")
    @classmethod
    def normalize_payment_method(cls, value: str) -> str:
        return value.strip().lower()


class OrderCreateResponse(BaseModel):
    public_id: UUID
    status: OrderStatus
    amount: int
    currency: str
    payment_method: str
    provider: str
    redirect_url: str | None
    instructions: str | None
    created_at: datetime


class OrderStatusResponse(BaseModel):
    public_id: UUID
    status: OrderStatus
    amount: int
    currency: str
    payment_method: str
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
    payment_method: str
    payment_url: str | None
    payment_instructions: str | None
    paid_at: datetime | None
    created_at: datetime


class AdminOrderListResponse(BaseModel):
    items: list[AdminOrderRead]
    total: int
    page: int
    page_size: int
    pages: int
