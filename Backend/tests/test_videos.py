import hashlib
import hmac
import json
import time
from typing import Any, cast
from uuid import UUID

from app.core.security import create_token_pair
from app.models.enums import UserRole, VideoProviderType, VideoStatus
from app.services.video_provider import DirectUpload, VideoMetadata
from httpx import AsyncClient

from tests.conftest import TEST_WEBHOOK_SECRET
from tests.support import InMemoryAdminRepository, InMemorySettingsRepository, seed_user
from tests.support_video import FakeCloudflareStreamProvider, InMemoryVideoRepository

PASSWORD = "Password123!"
PDF_CONTENT = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
PNG_CONTENT = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


async def login(client: AsyncClient, email: str, password: str = PASSWORD) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    return str(response.json()["access_token"])


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def create_ebook(
    client: AsyncClient, token: str, title: str = "Vidéo test"
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/admin/ebooks",
        headers=auth_header(token),
        json={"title": title, "description": "Une description.", "price": 5000},
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


async def publish_ebook(client: AsyncClient, token: str, ebook_id: str) -> None:
    pdf = await client.post(
        f"/api/v1/admin/ebooks/{ebook_id}/pdf",
        headers=auth_header(token),
        files={"file": ("source.pdf", PDF_CONTENT, "application/pdf")},
    )
    assert pdf.status_code == 200
    cover = await client.post(
        f"/api/v1/admin/ebooks/{ebook_id}/cover",
        headers=auth_header(token),
        files={"file": ("cover.png", PNG_CONTENT, "image/png")},
    )
    assert cover.status_code == 200
    published = await client.post(
        f"/api/v1/admin/ebooks/{ebook_id}/publish",
        headers=auth_header(token),
    )
    assert published.status_code == 200


def webhook_payload(
    video_id: str,
    state: str = "ready",
    duration: float = 95.4,
) -> dict[str, Any]:
    return {
        "uid": video_id,
        "readyToStream": state == "ready",
        "status": {"state": state},
        "duration": duration,
        "thumbnail": f"https://cdn.cloudflare.test/{video_id}/thumb.jpg",
        "playback": {"hls": f"https://cdn.cloudflare.test/{video_id}/manifest.m3u8"},
    }


def sign_webhook(body: bytes, secret: str = TEST_WEBHOOK_SECRET) -> str:
    timestamp = int(time.time())
    digest = hmac.new(
        secret.encode(),
        f"{timestamp}.".encode() + body,
        hashlib.sha256,
    ).hexdigest()
    return f"time={timestamp},sig1={digest}"


async def send_webhook(
    client: AsyncClient,
    payload: dict[str, Any],
    *,
    signature: str | None = None,
) -> Any:
    body = json.dumps(payload).encode()
    return await client.post(
        "/api/v1/webhooks/cloudflare-stream",
        content=body,
        headers={"Webhook-Signature": signature or sign_webhook(body)},
    )


async def create_upload(
    client: AsyncClient,
    token: str,
    ebook_id: str,
) -> dict[str, Any]:
    response = await client.post(
        f"/api/v1/admin/ebooks/{ebook_id}/video/upload-url",
        headers=auth_header(token),
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


async def test_upload_url_creates_uploading_video(
    catalog_client: AsyncClient,
    repository: InMemoryAdminRepository,
    video_repository: InMemoryVideoRepository,
) -> None:
    await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)
    token = await login(catalog_client, "admin@prebook.io")
    ebook = await create_ebook(catalog_client, token)

    ticket = await create_upload(catalog_client, token, ebook["id"])

    assert ticket["upload_url"] == "https://upload.cloudflare.test/direct"
    assert ticket["provider_video_id"] == "cf-video-1"
    video = video_repository.videos[UUID(ticket["video_id"])]
    assert video.status is VideoStatus.UPLOADING
    assert video.provider is VideoProviderType.CLOUDFLARE_STREAM
    assert video.provider_video_id == "cf-video-1"
    stored_ebook = (
        video_repository.ebook_lookup(video.ebook_id) if video_repository.ebook_lookup else None
    )
    assert stored_ebook is not None
    assert stored_ebook.preview_video_id is None


async def test_webhook_valid_invalid_and_replayed(
    catalog_client: AsyncClient,
    repository: InMemoryAdminRepository,
    video_repository: InMemoryVideoRepository,
    cloudflare_provider: FakeCloudflareStreamProvider,
) -> None:
    await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)
    token = await login(catalog_client, "admin@prebook.io")
    ebook = await create_ebook(catalog_client, token)
    ticket = await create_upload(catalog_client, token, ebook["id"])

    invalid = await send_webhook(
        catalog_client,
        webhook_payload(ticket["provider_video_id"]),
        signature="time=1,sig1=deadbeef",
    )
    assert invalid.status_code == 403

    valid = await send_webhook(catalog_client, webhook_payload(ticket["provider_video_id"]))
    assert valid.status_code == 204

    video = video_repository.videos[UUID(ticket["video_id"])]
    assert video.status is VideoStatus.READY
    assert video.duration_seconds == 95
    assert video.thumbnail_url is not None
    assert video.hls_url is not None
    stored_ebook = (
        video_repository.ebook_lookup(video.ebook_id) if video_repository.ebook_lookup else None
    )
    assert stored_ebook is not None
    assert stored_ebook.preview_video_id == video.id

    replay = await send_webhook(catalog_client, webhook_payload(ticket["provider_video_id"]))
    assert replay.status_code == 204
    assert video.status is VideoStatus.READY
    assert stored_ebook.preview_video_id == video.id
    assert cloudflare_provider.deleted == []


async def test_webhook_is_exempt_from_maintenance(
    catalog_client: AsyncClient,
    repository: InMemoryAdminRepository,
    settings_repository: InMemorySettingsRepository,
) -> None:
    await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)
    token = await login(catalog_client, "admin@prebook.io")
    ebook = await create_ebook(catalog_client, token)
    ticket = await create_upload(catalog_client, token, ebook["id"])
    settings_repository.values["maintenance_mode"] = True

    response = await send_webhook(catalog_client, webhook_payload(ticket["provider_video_id"]))

    assert response.status_code == 204


async def test_refresh_synchronizes_cloudflare_status(
    catalog_client: AsyncClient,
    repository: InMemoryAdminRepository,
    video_repository: InMemoryVideoRepository,
    cloudflare_provider: FakeCloudflareStreamProvider,
) -> None:
    await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)
    token = await login(catalog_client, "admin@prebook.io")
    ebook = await create_ebook(catalog_client, token)
    ticket = await create_upload(catalog_client, token, ebook["id"])

    cloudflare_provider.metadata = VideoMetadata(
        status=VideoStatus.READY,
        duration_seconds=61,
        thumbnail_url="https://cdn.cloudflare.test/refresh.jpg",
        hls_url="https://cdn.cloudflare.test/refresh.m3u8",
    )

    response = await catalog_client.post(
        f"/api/v1/admin/videos/{ticket['video_id']}/refresh",
        headers=auth_header(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["duration_seconds"] == 61
    assert body["embed_url"] == f"https://iframe.videodelivery.net/{ticket['provider_video_id']}"
    assert cloudflare_provider.fetch_calls == 1
    video = video_repository.videos[UUID(ticket["video_id"])]
    assert video.status is VideoStatus.READY


async def test_replacement_switches_active_video_and_deletes_previous(
    catalog_client: AsyncClient,
    repository: InMemoryAdminRepository,
    video_repository: InMemoryVideoRepository,
    cloudflare_provider: FakeCloudflareStreamProvider,
) -> None:
    await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)
    token = await login(catalog_client, "admin@prebook.io")
    ebook = await create_ebook(catalog_client, token)

    first = await create_upload(catalog_client, token, ebook["id"])
    await send_webhook(catalog_client, webhook_payload(first["provider_video_id"]))
    first_video = video_repository.videos[UUID(first["video_id"])]
    stored_ebook = (
        video_repository.ebook_lookup(first_video.ebook_id)
        if video_repository.ebook_lookup
        else None
    )
    assert stored_ebook is not None
    assert stored_ebook.preview_video_id == first_video.id

    cloudflare_provider.upload = DirectUpload(
        upload_url="https://upload.cloudflare.test/second",
        provider_video_id="cf-video-2",
    )
    second = await create_upload(catalog_client, token, ebook["id"])
    assert stored_ebook.preview_video_id == first_video.id

    await send_webhook(catalog_client, webhook_payload(second["provider_video_id"]))

    second_video = video_repository.videos[UUID(second["video_id"])]
    assert stored_ebook.preview_video_id == second_video.id
    assert first_video.id not in video_repository.videos
    assert cloudflare_provider.deleted == ["cf-video-1"]


async def test_detach_deletes_video_remotely_and_clears_preview(
    catalog_client: AsyncClient,
    repository: InMemoryAdminRepository,
    video_repository: InMemoryVideoRepository,
    cloudflare_provider: FakeCloudflareStreamProvider,
) -> None:
    await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)
    token = await login(catalog_client, "admin@prebook.io")
    ebook = await create_ebook(catalog_client, token)
    ticket = await create_upload(catalog_client, token, ebook["id"])
    await send_webhook(catalog_client, webhook_payload(ticket["provider_video_id"]))

    response = await catalog_client.delete(
        f"/api/v1/admin/ebooks/{ebook['id']}/video",
        headers=auth_header(token),
    )

    assert response.status_code == 204
    assert video_repository.videos == {}
    assert cloudflare_provider.deleted == [ticket["provider_video_id"]]
    stored = (
        video_repository.ebook_lookup(UUID(ebook["id"])) if video_repository.ebook_lookup else None
    )
    assert stored is not None
    assert stored.preview_video_id is None


async def test_external_video_validates_url_and_builds_embed(
    catalog_client: AsyncClient,
    repository: InMemoryAdminRepository,
    video_repository: InMemoryVideoRepository,
) -> None:
    await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)
    token = await login(catalog_client, "admin@prebook.io")
    ebook = await create_ebook(catalog_client, token)

    invalid = await catalog_client.post(
        f"/api/v1/admin/ebooks/{ebook['id']}/video/external",
        headers=auth_header(token),
        json={"url": "https://example.com/video"},
    )
    assert invalid.status_code == 400

    response = await catalog_client.post(
        f"/api/v1/admin/ebooks/{ebook['id']}/video/external",
        headers=auth_header(token),
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ready"
    assert body["provider"] == "external_url"
    assert body["embed_url"] == "https://www.youtube.com/embed/dQw4w9WgXcQ"
    video = video_repository.videos[UUID(body["id"])]
    stored = (
        video_repository.ebook_lookup(video.ebook_id) if video_repository.ebook_lookup else None
    )
    assert stored is not None
    assert stored.preview_video_id == video.id


async def test_public_detail_exposes_video_only_when_ready(
    catalog_client: AsyncClient,
    repository: InMemoryAdminRepository,
) -> None:
    await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)
    token = await login(catalog_client, "admin@prebook.io")
    ebook = await create_ebook(catalog_client, token, title="Livre avec vidéo")
    await publish_ebook(catalog_client, token, ebook["id"])
    ticket = await create_upload(catalog_client, token, ebook["id"])

    pending = await catalog_client.get(f"/api/v1/ebooks/{ebook['slug']}")
    assert pending.status_code == 200
    assert pending.json()["video"] is None

    processing = await send_webhook(
        catalog_client,
        webhook_payload(ticket["provider_video_id"], state="inprogress"),
    )
    assert processing.status_code == 204
    still_pending = await catalog_client.get(f"/api/v1/ebooks/{ebook['slug']}")
    assert still_pending.json()["video"] is None

    ready = await send_webhook(
        catalog_client,
        webhook_payload(ticket["provider_video_id"]),
    )
    assert ready.status_code == 204
    detail = await catalog_client.get(f"/api/v1/ebooks/{ebook['slug']}")
    video = detail.json()["video"]
    assert video is not None
    assert video["provider"] == "cloudflare_stream"
    assert (
        video["hls_url"]
        == f"https://cdn.cloudflare.test/{ticket['provider_video_id']}/manifest.m3u8"
    )
    assert video["thumbnail_url"] is not None
    assert video["duration_seconds"] == 95
    assert video["embed_url"] is not None


async def test_video_admin_routes_require_admin_rights(
    catalog_client: AsyncClient,
    repository: InMemoryAdminRepository,
) -> None:
    customer = await seed_user(repository, "customer@prebook.io", UserRole.CUSTOMER)
    customer_token = create_token_pair(str(customer.id), {"role": customer.role.value})

    anonymous = await catalog_client.post(
        "/api/v1/admin/ebooks/00000000-0000-0000-0000-000000000000/video/upload-url",
    )
    forbidden = await catalog_client.post(
        "/api/v1/admin/ebooks/00000000-0000-0000-0000-000000000000/video/upload-url",
        headers=auth_header(customer_token.access_token),
    )

    assert anonymous.status_code == 401
    assert forbidden.status_code == 403
