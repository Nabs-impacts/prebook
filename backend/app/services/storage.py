import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import aioboto3

from app.core.config import get_settings

R2_REGION = "auto"
COVER_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".webp": "image/webp",
}


@dataclass(frozen=True, slots=True)
class StoredFile:
    key: str
    url: str | None


class StorageBackend(ABC):
    @abstractmethod
    async def save_pdf(self, content: bytes, extension: str) -> StoredFile: ...

    @abstractmethod
    async def save_cover(self, content: bytes, extension: str) -> StoredFile: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    async def presigned_download_url(
        self,
        key: str,
        expires_in_seconds: int | None = None,
    ) -> str:
        raise NotImplementedError


class LocalStorageBackend(StorageBackend):
    def __init__(
        self,
        private_dir: Path,
        public_dir: Path,
        public_url: str,
    ) -> None:
        self._private_dir = private_dir.resolve()
        self._public_dir = public_dir.resolve()
        self._public_url = public_url.rstrip("/")
        self.ensure_directories()

    @property
    def private_dir(self) -> Path:
        return self._private_dir

    @property
    def public_dir(self) -> Path:
        return self._public_dir

    def ensure_directories(self) -> None:
        (self._private_dir / "pdfs").mkdir(parents=True, exist_ok=True)
        (self._public_dir / "covers").mkdir(parents=True, exist_ok=True)

    async def save_pdf(self, content: bytes, extension: str) -> StoredFile:
        name = f"{uuid4().hex}{extension}"
        relative_key = f"pdfs/{name}"
        target = self._private_dir / relative_key
        await asyncio.to_thread(target.write_bytes, content)
        return StoredFile(key=relative_key, url=None)

    async def save_cover(self, content: bytes, extension: str) -> StoredFile:
        name = f"{uuid4().hex}{extension}"
        relative_key = f"covers/{name}"
        target = self._public_dir / relative_key
        await asyncio.to_thread(target.write_bytes, content)
        return StoredFile(key=relative_key, url=f"{self._public_url}/{relative_key}")

    async def delete(self, key: str) -> None:
        for root in (self._private_dir, self._public_dir):
            target = (root / key).resolve()
            if not target.is_relative_to(root):
                continue
            if target.is_file():
                await asyncio.to_thread(target.unlink)


class R2StorageBackend(StorageBackend):
    def __init__(
        self,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        public_base_url: str,
        presigned_ttl_seconds: int,
        session: Any | None = None,
    ) -> None:
        self._account_id = account_id
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._bucket = bucket
        self._public_base_url = public_base_url.rstrip("/")
        self._presigned_ttl_seconds = presigned_ttl_seconds
        self._session = session if session is not None else aioboto3.Session()

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[Any]:
        async with self._session.client(
            "s3",
            endpoint_url=f"https://{self._account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=self._access_key_id,
            aws_secret_access_key=self._secret_access_key,
            region_name=R2_REGION,
        ) as client:
            yield client

    async def _put(self, key: str, content: bytes, content_type: str) -> None:
        async with self._client() as client:
            await client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
            )

    async def save_pdf(self, content: bytes, extension: str) -> StoredFile:
        key = f"pdfs/{uuid4().hex}{extension}"
        await self._put(key, content, "application/pdf")
        return StoredFile(key=key, url=None)

    async def save_cover(self, content: bytes, extension: str) -> StoredFile:
        key = f"covers/{uuid4().hex}{extension}"
        content_type = COVER_CONTENT_TYPES.get(extension, "application/octet-stream")
        await self._put(key, content, content_type)
        return StoredFile(key=key, url=f"{self._public_base_url}/{key}")

    async def delete(self, key: str) -> None:
        async with self._client() as client:
            await client.delete_object(Bucket=self._bucket, Key=key)

    async def presigned_download_url(
        self,
        key: str,
        expires_in_seconds: int | None = None,
    ) -> str:
        ttl = expires_in_seconds if expires_in_seconds is not None else self._presigned_ttl_seconds
        async with self._client() as client:
            url = await client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=ttl,
            )
        return str(url)


def _require(value: str | None, name: str) -> str:
    if not value:
        raise ValueError(f"La variable {name} est requise pour le backend R2.")
    return value


def get_storage_backend() -> StorageBackend:
    settings = get_settings()
    if settings.STORAGE_BACKEND == "r2":
        return R2StorageBackend(
            account_id=_require(settings.R2_ACCOUNT_ID, "R2_ACCOUNT_ID"),
            access_key_id=_require(settings.R2_ACCESS_KEY_ID, "R2_ACCESS_KEY_ID"),
            secret_access_key=_require(settings.R2_SECRET_ACCESS_KEY, "R2_SECRET_ACCESS_KEY"),
            bucket=_require(settings.R2_BUCKET, "R2_BUCKET"),
            public_base_url=_require(settings.R2_PUBLIC_BASE_URL, "R2_PUBLIC_BASE_URL"),
            presigned_ttl_seconds=settings.PRESIGNED_URL_TTL_SECONDS,
        )
    return LocalStorageBackend(
        settings.storage_private_dir,
        settings.storage_public_dir,
        settings.STORAGE_PUBLIC_URL,
    )
