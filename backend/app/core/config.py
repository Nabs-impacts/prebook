from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", Path(".env")),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    APP_NAME: str = "Prebook API"
    ENV: Literal["local", "development", "staging", "production", "test"] = "local"
    SECRET_KEY: str = Field(min_length=32)
    DATABASE_URL: str
    REDIS_URL: str
    CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:5173"]
    )
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = Field(default=10, ge=1)
    DB_MAX_OVERFLOW: int = Field(default=20, ge=0)
    DB_POOL_RECYCLE_SECONDS: int = Field(default=1800, ge=0)
    ACCESS_TOKEN_TTL_MINUTES: int = Field(default=15, ge=1)
    REFRESH_TOKEN_TTL_DAYS: int = Field(default=7, ge=1)
    LOGIN_RATE_LIMIT_ATTEMPTS: int = Field(default=5, ge=1)
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = Field(default=60, ge=1)
    REVIEW_RATE_LIMIT_ATTEMPTS: int = Field(default=3, ge=1)
    REVIEW_RATE_LIMIT_WINDOW_SECONDS: int = Field(default=3600, ge=1)
    PASSWORD_MIN_LENGTH: int = Field(default=8, ge=8)
    STORAGE_ROOT: Path = Path("storage")
    STORAGE_PUBLIC_URL: str = "/media"
    STORAGE_BACKEND: Literal["local", "r2"] = "local"
    MAX_PDF_UPLOAD_BYTES: int = Field(default=50 * 1024 * 1024, ge=1)
    MAX_COVER_UPLOAD_BYTES: int = Field(default=5 * 1024 * 1024, ge=1)
    R2_ACCOUNT_ID: str | None = None
    R2_ACCESS_KEY_ID: str | None = None
    R2_SECRET_ACCESS_KEY: str | None = None
    R2_BUCKET: str | None = None
    R2_PUBLIC_BASE_URL: str | None = None
    PRESIGNED_URL_TTL_SECONDS: int = Field(default=300, ge=1)
    CLOUDFLARE_ACCOUNT_ID: str | None = None
    CLOUDFLARE_STREAM_API_TOKEN: str | None = None
    CLOUDFLARE_STREAM_WEBHOOK_SECRET: str | None = None
    VIDEO_MAX_DURATION_SECONDS: int = Field(default=600, ge=1)
    VIDEO_MAX_SIZE_BYTES: int = Field(default=500 * 1024 * 1024, ge=1)

    @property
    def storage_private_dir(self) -> Path:
        return (self.STORAGE_ROOT / "private").resolve()

    @property
    def storage_public_dir(self) -> Path:
        return (self.STORAGE_ROOT / "public").resolve()

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def split_cors_origins(cls, value: object) -> list[str]:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped == "*":
                return ["*"]
            return [origin.strip() for origin in stripped.split(",") if origin.strip()]
        if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
            return [str(origin) for origin in value]
        raise ValueError("CORS_ORIGINS doit être une chaîne ou une séquence")


@lru_cache
def get_settings() -> Settings:
    return Settings()
