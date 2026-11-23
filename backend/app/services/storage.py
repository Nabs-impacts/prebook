import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.core.config import get_settings


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


def get_storage_backend() -> StorageBackend:
    settings = get_settings()
    return LocalStorageBackend(
        settings.storage_private_dir,
        settings.storage_public_dir,
        settings.STORAGE_PUBLIC_URL,
    )
