from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.core.config import get_settings
from app.models.enums import UserRole


def validate_password(value: str) -> str:
    minimum = get_settings().PASSWORD_MIN_LENGTH
    if len(value) < minimum:
        raise ValueError(f"Le mot de passe doit contenir au moins {minimum} caractères.")
    return value


class AdminCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    role: UserRole = UserRole.ADMIN

    @field_validator("password")
    @classmethod
    def check_password(cls, value: str) -> str:
        return validate_password(value)

    @field_validator("role")
    @classmethod
    def check_role(cls, value: UserRole) -> UserRole:
        if value is UserRole.CUSTOMER:
            raise ValueError("Le rôle doit être admin ou super_admin.")
        return value


class AdminUpdate(BaseModel):
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("password")
    @classmethod
    def check_password(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_password(value)

    @model_validator(mode="after")
    def check_at_least_one_field(self) -> "AdminUpdate":
        if self.is_active is None and self.password is None:
            raise ValueError("Aucune modification fournie.")
        return self


class AdminRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    role: UserRole
    is_active: bool
    created_at: datetime


class AdminListResponse(BaseModel):
    items: list[AdminRead]
    total: int
    page: int
    page_size: int
    pages: int
