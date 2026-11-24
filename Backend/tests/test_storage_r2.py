from typing import Any

import pytest
from app.core.config import get_settings
from app.services.storage import R2StorageBackend, get_storage_backend


class FakeS3Client:
    def __init__(self) -> None:
        self.puts: list[dict[str, Any]] = []
        self.deletes: list[dict[str, Any]] = []
        self.presigns: list[tuple[str, dict[str, Any], int]] = []

    async def put_object(self, **kwargs: Any) -> None:
        self.puts.append(kwargs)

    async def delete_object(self, **kwargs: Any) -> None:
        self.deletes.append(kwargs)

    async def generate_presigned_url(
        self,
        operation: str,
        Params: dict[str, Any],
        ExpiresIn: int,
    ) -> str:
        self.presigns.append((operation, Params, ExpiresIn))
        return "https://r2.test/presigned"


class FakeClientContext:
    def __init__(self, client: FakeS3Client) -> None:
        self._client = client

    async def __aenter__(self) -> FakeS3Client:
        return self._client

    async def __aexit__(self, *args: object) -> None:
        return None


class FakeSession:
    def __init__(self, client: FakeS3Client) -> None:
        self._client = client
        self.client_kwargs: dict[str, Any] = {}

    def client(self, service_name: str, **kwargs: Any) -> FakeClientContext:
        self.client_kwargs = {"service_name": service_name, **kwargs}
        return FakeClientContext(self._client)


def build_backend(client: FakeS3Client) -> R2StorageBackend:
    return R2StorageBackend(
        account_id="account",
        access_key_id="access",
        secret_access_key="secret",
        bucket="bucket",
        public_base_url="https://cdn.prebook.test",
        presigned_ttl_seconds=300,
        session=FakeSession(client),
    )


async def test_r2_stores_pdf_privately_and_cover_publicly() -> None:
    client = FakeS3Client()
    backend = build_backend(client)

    pdf = await backend.save_pdf(b"%PDF-1.4", ".pdf")
    cover = await backend.save_cover(b"\x89PNG\r\n\x1a\n", ".png")

    assert pdf.key.startswith("pdfs/")
    assert pdf.url is None
    assert cover.key.startswith("covers/")
    assert cover.url is not None
    assert cover.url.startswith("https://cdn.prebook.test/covers/")
    assert client.puts[0]["Bucket"] == "bucket"
    assert client.puts[0]["Key"] == pdf.key
    assert client.puts[0]["ContentType"] == "application/pdf"
    assert client.puts[1]["ContentType"] == "image/png"


async def test_r2_generates_short_lived_presigned_urls() -> None:
    client = FakeS3Client()
    backend = build_backend(client)

    url = await backend.presigned_download_url("pdfs/book.pdf", 60)

    assert url == "https://r2.test/presigned"
    operation, params, expires_in = client.presigns[0]
    assert operation == "get_object"
    assert params == {"Bucket": "bucket", "Key": "pdfs/book.pdf"}
    assert expires_in == 60


async def test_r2_delete_removes_object() -> None:
    client = FakeS3Client()
    backend = build_backend(client)

    await backend.delete("pdfs/book.pdf")

    assert client.deletes == [{"Bucket": "bucket", "Key": "pdfs/book.pdf"}]


def test_storage_backend_selection_uses_r2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORAGE_BACKEND", "r2")
    monkeypatch.setenv("R2_ACCOUNT_ID", "account")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "access")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("R2_BUCKET", "bucket")
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://cdn.prebook.test")
    get_settings.cache_clear()
    try:
        backend = get_storage_backend()
        assert isinstance(backend, R2StorageBackend)
    finally:
        get_settings.cache_clear()
