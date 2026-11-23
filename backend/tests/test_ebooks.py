from typing import Any, cast
from uuid import UUID

from app.core.security import create_token_pair
from app.models.enums import UserRole
from app.services.storage import LocalStorageBackend
from fastapi import FastAPI
from httpx import AsyncClient

from tests.support import InMemoryAdminRepository, InMemorySettingsRepository, seed_user
from tests.support_catalog import (
    InMemoryEbookRepository,
    InMemoryOrderRepository,
    InMemoryReviewRepository,
)

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
    client: AsyncClient,
    token: str,
    *,
    title: str = "Guide du créateur",
    description: str = "Une description complète et détaillée.",
    summary: str | None = "Résumé court.",
    price: int = 5000,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": title,
        "description": description,
        "price": price,
    }
    if summary is not None:
        payload["summary"] = summary
    response = await client.post(
        "/api/v1/admin/ebooks",
        headers=auth_header(token),
        json=payload,
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


async def upload_assets(
    client: AsyncClient,
    token: str,
    ebook_id: str,
) -> dict[str, Any]:
    pdf_response = await client.post(
        f"/api/v1/admin/ebooks/{ebook_id}/pdf",
        headers=auth_header(token),
        files={"file": ("source.pdf", PDF_CONTENT, "application/pdf")},
    )
    assert pdf_response.status_code == 200
    cover_response = await client.post(
        f"/api/v1/admin/ebooks/{ebook_id}/cover",
        headers=auth_header(token),
        files={"file": ("cover.png", PNG_CONTENT, "image/png")},
    )
    assert cover_response.status_code == 200
    return cast(dict[str, Any], cover_response.json())


async def create_published_ebook(
    client: AsyncClient,
    token: str,
    **kwargs: Any,
) -> dict[str, Any]:
    ebook = await create_ebook(client, token, **kwargs)
    await upload_assets(client, token, ebook["id"])
    response = await client.post(
        f"/api/v1/admin/ebooks/{ebook['id']}/publish",
        headers=auth_header(token),
    )
    assert response.status_code == 200
    return cast(dict[str, Any], response.json())


async def test_public_list_and_detail_expose_light_and_full_fields(
    catalog_client: AsyncClient,
    repository: InMemoryAdminRepository,
) -> None:
    await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)
    token = await login(catalog_client, "admin@prebook.io")
    ebook = await create_published_ebook(
        catalog_client,
        token,
        title="Créer sa marque",
        description="La description complète du livre.",
        summary="Un résumé court.",
        price=7500,
    )

    listing = await catalog_client.get("/api/v1/ebooks")

    assert listing.status_code == 200
    assert listing.headers["cache-control"] == "public, max-age=60"
    assert listing.headers["etag"].startswith('"')
    body = listing.json()
    assert body["total"] == 1
    assert body["pages"] == 1
    item = body["items"][0]
    assert item["id"] == ebook["id"]
    assert item["title"] == "Créer sa marque"
    assert item["slug"] == "creer-sa-marque"
    assert item["price"] == 7500
    assert item["cover_url"].startswith("/media/covers/")
    assert item["summary"] == "Un résumé court."
    assert item["reviews_count"] == 0
    assert item["purchases_count"] == 0
    assert "description" not in item

    detail = await catalog_client.get(f"/api/v1/ebooks/{ebook['slug']}")

    assert detail.status_code == 200
    assert detail.headers["cache-control"] == "public, max-age=60"
    detail_body = detail.json()
    assert detail_body["description"] == "La description complète du livre."
    assert detail_body["average_rating"] is None
    assert detail_body["preview_video_id"] is None
    assert detail_body["reviews_count"] == 0
    assert detail_body["purchases_count"] == 0

    not_modified = await catalog_client.get(
        "/api/v1/ebooks",
        headers={"If-None-Match": listing.headers["etag"]},
    )
    assert not_modified.status_code == 304
    assert not_modified.content == b""


async def test_unpublished_ebook_is_invisible(
    catalog_client: AsyncClient,
    repository: InMemoryAdminRepository,
) -> None:
    await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)
    token = await login(catalog_client, "admin@prebook.io")
    ebook = await create_ebook(catalog_client, token, title="Brouillon secret")

    listing = await catalog_client.get("/api/v1/ebooks")
    detail = await catalog_client.get(f"/api/v1/ebooks/{ebook['slug']}")
    reviews = await catalog_client.get(f"/api/v1/ebooks/{ebook['slug']}/reviews")

    assert listing.status_code == 200
    assert listing.json()["items"] == []
    assert detail.status_code == 404
    assert reviews.status_code == 404


async def test_review_creation_is_pending_sanitized_and_rate_limited(
    catalog_client: AsyncClient,
    repository: InMemoryAdminRepository,
    review_repository: InMemoryReviewRepository,
) -> None:
    await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)
    token = await login(catalog_client, "admin@prebook.io")
    ebook = await create_published_ebook(catalog_client, token)

    response = await catalog_client.post(
        f"/api/v1/ebooks/{ebook['slug']}/reviews",
        json={
            "author_name": "<script>alert(1)</script>Ada",
            "rating": 5,
            "comment": "<b>Excellent</b><script>alert('xss')</script>",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert "<script>" not in body["author_name"]
    assert "<b>" not in body["comment"]
    assert "<script>" not in body["comment"]
    assert body["author_name"] == "alert(1)Ada"
    assert body["comment"] == "Excellentalert('xss')"
    assert "is_approved" not in body

    stored = next(iter(review_repository.reviews.values()))
    assert stored.is_approved is False

    public_reviews = await catalog_client.get(f"/api/v1/ebooks/{ebook['slug']}/reviews")
    assert public_reviews.json()["items"] == []

    for index in range(2):
        accepted = await catalog_client.post(
            f"/api/v1/ebooks/{ebook['slug']}/reviews",
            json={"author_name": f"Auteur {index}", "rating": 4, "comment": "Bien."},
        )
        assert accepted.status_code == 201

    limited = await catalog_client.post(
        f"/api/v1/ebooks/{ebook['slug']}/reviews",
        json={"author_name": "Auteur 4", "rating": 4},
    )
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "too_many_requests"


async def test_review_moderation_updates_public_views_and_counters(
    catalog_client: AsyncClient,
    repository: InMemoryAdminRepository,
) -> None:
    await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)
    token = await login(catalog_client, "admin@prebook.io")
    ebook = await create_published_ebook(catalog_client, token)

    await catalog_client.post(
        f"/api/v1/ebooks/{ebook['slug']}/reviews",
        json={"author_name": "Ada", "rating": 5, "comment": "Superbe."},
    )
    await catalog_client.post(
        f"/api/v1/ebooks/{ebook['slug']}/reviews",
        json={"author_name": "Bob", "rating": 3, "comment": "Correct."},
    )

    pending = await catalog_client.get(
        "/api/v1/admin/reviews",
        headers=auth_header(token),
    )
    assert pending.status_code == 200
    assert pending.json()["total"] == 2
    assert pending.json()["items"][0]["ebook_title"] == ebook["title"]

    first_review_id = pending.json()["items"][0]["id"]
    approved = await catalog_client.post(
        f"/api/v1/admin/reviews/{first_review_id}/approve",
        headers=auth_header(token),
    )
    assert approved.status_code == 200

    public_reviews = await catalog_client.get(f"/api/v1/ebooks/{ebook['slug']}/reviews")
    assert public_reviews.status_code == 200
    assert public_reviews.json()["total"] == 1
    assert public_reviews.json()["items"][0]["author_name"] in {"Ada", "Bob"}

    detail = await catalog_client.get(f"/api/v1/ebooks/{ebook['slug']}")
    assert detail.json()["reviews_count"] == 1
    assert detail.json()["average_rating"] in {3.0, 5.0}

    approved_list = await catalog_client.get(
        "/api/v1/admin/reviews?status=approved",
        headers=auth_header(token),
    )
    assert approved_list.json()["total"] == 1

    deleted = await catalog_client.delete(
        f"/api/v1/admin/reviews/{first_review_id}",
        headers=auth_header(token),
    )
    assert deleted.status_code == 204

    empty_reviews = await catalog_client.get(f"/api/v1/ebooks/{ebook['slug']}/reviews")
    assert empty_reviews.json()["total"] == 0
    detail_after = await catalog_client.get(f"/api/v1/ebooks/{ebook['slug']}")
    assert detail_after.json()["reviews_count"] == 0
    assert detail_after.json()["average_rating"] is None


async def test_disabled_counters_return_null_without_count_queries(
    catalog_client: AsyncClient,
    repository: InMemoryAdminRepository,
    review_repository: InMemoryReviewRepository,
    order_repository: InMemoryOrderRepository,
) -> None:
    await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)
    token = await login(catalog_client, "admin@prebook.io")
    ebook = await create_published_ebook(catalog_client, token)

    await catalog_client.patch(
        "/api/v1/admin/settings",
        headers=auth_header(token),
        json={"show_reviews_count": False, "show_purchases_count": False},
    )
    review_repository.count_approved_by_ebooks_calls = 0
    review_repository.count_approved_calls = 0
    order_repository.count_paid_by_ebooks_calls = 0
    order_repository.count_paid_by_ebook_calls = 0

    listing = await catalog_client.get("/api/v1/ebooks")
    detail = await catalog_client.get(f"/api/v1/ebooks/{ebook['slug']}")

    assert listing.json()["items"][0]["reviews_count"] is None
    assert listing.json()["items"][0]["purchases_count"] is None
    assert detail.json()["reviews_count"] is None
    assert detail.json()["purchases_count"] is None
    assert review_repository.count_approved_by_ebooks_calls == 0
    assert review_repository.count_approved_calls == 0
    assert order_repository.count_paid_by_ebooks_calls == 0
    assert order_repository.count_paid_by_ebook_calls == 0

    order_repository.paid_counts[UUID(ebook["id"])] = 2
    await catalog_client.patch(
        "/api/v1/admin/settings",
        headers=auth_header(token),
        json={"show_reviews_count": True, "show_purchases_count": True},
    )

    enabled = await catalog_client.get(f"/api/v1/ebooks/{ebook['slug']}")
    assert enabled.json()["reviews_count"] == 0
    assert enabled.json()["purchases_count"] == 2


async def test_list_and_detail_cache_are_invalidated_by_admin_update(
    catalog_client: AsyncClient,
    repository: InMemoryAdminRepository,
    ebook_repository: InMemoryEbookRepository,
) -> None:
    await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)
    token = await login(catalog_client, "admin@prebook.io")
    ebook = await create_published_ebook(catalog_client, token, price=5000)

    first = await catalog_client.get("/api/v1/ebooks")
    second = await catalog_client.get("/api/v1/ebooks")
    assert first.json() == second.json()
    assert ebook_repository.list_published_calls == 1

    updated = await catalog_client.patch(
        f"/api/v1/admin/ebooks/{ebook['id']}",
        headers=auth_header(token),
        json={"price": 9000},
    )
    assert updated.status_code == 200
    assert updated.json()["price"] == 9000

    third = await catalog_client.get("/api/v1/ebooks")
    assert third.json()["items"][0]["price"] == 9000
    assert ebook_repository.list_published_calls == 2

    detail_first = await catalog_client.get(f"/api/v1/ebooks/{ebook['slug']}")
    detail_second = await catalog_client.get(f"/api/v1/ebooks/{ebook['slug']}")
    assert detail_first.json() == detail_second.json()


async def test_admin_routes_require_admin_rights(
    catalog_client: AsyncClient,
    repository: InMemoryAdminRepository,
) -> None:
    customer = await seed_user(repository, "customer@prebook.io", UserRole.CUSTOMER)
    customer_token = create_token_pair(str(customer.id), {"role": customer.role.value})

    anonymous = await catalog_client.get("/api/v1/admin/ebooks")
    forbidden = await catalog_client.post(
        "/api/v1/admin/ebooks",
        headers=auth_header(customer_token.access_token),
        json={"title": "X", "description": "Y", "price": 1000},
    )

    assert anonymous.status_code == 401
    assert forbidden.status_code == 403
    assert customer.id is not None


async def test_slug_is_unique_and_upload_is_validated(
    catalog_client: AsyncClient,
    repository: InMemoryAdminRepository,
    storage_backend: LocalStorageBackend,
) -> None:
    await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)
    token = await login(catalog_client, "admin@prebook.io")

    first = await create_ebook(catalog_client, token, title="Même titre")
    second = await create_ebook(catalog_client, token, title="Même titre")
    assert first["slug"] == "meme-titre"
    assert second["slug"] == "meme-titre-2"

    too_early = await catalog_client.post(
        f"/api/v1/admin/ebooks/{first['id']}/publish",
        headers=auth_header(token),
    )
    assert too_early.status_code == 409

    invalid_pdf = await catalog_client.post(
        f"/api/v1/admin/ebooks/{first['id']}/pdf",
        headers=auth_header(token),
        files={"file": ("source.pdf", b"not a pdf", "application/pdf")},
    )
    assert invalid_pdf.status_code == 400

    uploaded = await upload_assets(catalog_client, token, first["id"])
    assert uploaded["has_pdf"] is True
    assert uploaded["cover_url"].startswith("/media/covers/")
    assert "pdf_storage_key" not in uploaded

    published = await catalog_client.post(
        f"/api/v1/admin/ebooks/{first['id']}/publish",
        headers=auth_header(token),
    )
    assert published.status_code == 200
    assert published.json()["is_published"] is True

    private_files = list((storage_backend.private_dir / "pdfs").glob("*.pdf"))
    public_files = list((storage_backend.public_dir / "covers").glob("*.png"))
    assert len(private_files) == 1
    assert len(public_files) == 1


async def test_delete_is_soft_when_orders_exist(
    catalog_client: AsyncClient,
    repository: InMemoryAdminRepository,
    ebook_repository: InMemoryEbookRepository,
    order_repository: InMemoryOrderRepository,
) -> None:
    await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)
    token = await login(catalog_client, "admin@prebook.io")

    without_orders = await create_ebook(catalog_client, token, title="Sans commande")
    deleted = await catalog_client.delete(
        f"/api/v1/admin/ebooks/{without_orders['id']}",
        headers=auth_header(token),
    )
    assert deleted.status_code == 204
    assert without_orders["id"] not in {str(ebook.id) for ebook in ebook_repository.ebooks.values()}

    with_orders = await create_ebook(catalog_client, token, title="Avec commande")
    order_repository.ebook_ids_with_orders.add(UUID(with_orders["id"]))
    soft_deleted = await catalog_client.delete(
        f"/api/v1/admin/ebooks/{with_orders['id']}",
        headers=auth_header(token),
    )
    assert soft_deleted.status_code == 204
    stored = next(
        ebook for ebook in ebook_repository.ebooks.values() if str(ebook.id) == with_orders["id"]
    )
    assert stored.deleted_at is not None
    assert stored.is_published is False

    admin_list = await catalog_client.get(
        "/api/v1/admin/ebooks",
        headers=auth_header(token),
    )
    assert admin_list.json()["items"] == []


async def test_public_reviews_only_include_approved_and_are_paginated(
    catalog_client: AsyncClient,
    repository: InMemoryAdminRepository,
    review_repository: InMemoryReviewRepository,
) -> None:
    await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)
    token = await login(catalog_client, "admin@prebook.io")
    ebook = await create_published_ebook(catalog_client, token)

    for index in range(3):
        response = await catalog_client.post(
            f"/api/v1/ebooks/{ebook['slug']}/reviews",
            json={"author_name": f"Auteur {index}", "rating": 5, "comment": "Top."},
        )
        assert response.status_code == 201

    for review in list(review_repository.reviews.values())[:2]:
        review.is_approved = True

    page = await catalog_client.get(
        f"/api/v1/ebooks/{ebook['slug']}/reviews?page=1&page_size=1",
    )

    assert page.status_code == 200
    assert page.json()["total"] == 2
    assert page.json()["pages"] == 2
    assert len(page.json()["items"]) == 1


def test_media_mount_is_registered(app: FastAPI) -> None:
    assert any(getattr(route, "path", None) == "/media" for route in app.routes)


async def test_settings_cache_repository_is_used_by_catalog(
    catalog_client: AsyncClient,
    repository: InMemoryAdminRepository,
    settings_repository: InMemorySettingsRepository,
) -> None:
    await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)
    token = await login(catalog_client, "admin@prebook.io")
    await create_published_ebook(catalog_client, token)

    settings_repository.cached = None
    await catalog_client.get("/api/v1/ebooks")
    first_load_count = settings_repository.load_count
    await catalog_client.get("/api/v1/ebooks")
    assert settings_repository.load_count == first_load_count
