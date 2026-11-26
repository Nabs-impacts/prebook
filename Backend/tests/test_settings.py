from typing import cast

from app.core.deps import get_health_service
from app.core.security import create_token_pair
from app.models.enums import AdminAuditAction, UserRole
from app.repositories.admin import AdminRepository
from app.repositories.settings import SettingsRepository
from app.schemas.health import DependencyStatus, HealthResponse, HealthStatus
from app.schemas.settings import (
    DEFAULT_MAINTENANCE_MESSAGE,
    SiteSettings,
    SiteSettingsUpdate,
)
from app.services.settings import SettingsService
from fastapi import FastAPI
from httpx import AsyncClient

from tests.support import InMemoryAdminRepository, InMemorySettingsRepository, seed_user

PASSWORD = "Password123!"


class HealthyService:
    async def check(self) -> HealthResponse:
        dependency = DependencyStatus(healthy=True, latency_ms=1.0)
        return HealthResponse(
            status=HealthStatus.OK,
            env="test",
            version="0.1.0",
            dependencies={"database": dependency, "redis": dependency},
        )


async def login(client: AsyncClient, email: str, password: str = PASSWORD) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    return str(response.json()["access_token"])


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_public_settings_returns_defaults(settings_client: AsyncClient) -> None:
    response = await settings_client.get("/api/v1/public/settings")

    assert response.status_code == 200
    assert response.json() == {
        "maintenance_mode": False,
        "maintenance_message": DEFAULT_MAINTENANCE_MESSAGE,
        "show_reviews_count": True,
        "show_purchases_count": True,
        "payments_enabled": True,
    }
    assert response.headers["cache-control"] == "public, max-age=30"
    assert response.headers["etag"].startswith('"')


async def test_admin_can_partially_update_settings_and_writes_audit(
    settings_client: AsyncClient,
    repository: InMemoryAdminRepository,
    settings_repository: InMemorySettingsRepository,
) -> None:
    actor = await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)
    token = await login(settings_client, "admin@prebook.io")

    response = await settings_client.patch(
        "/api/v1/admin/settings",
        headers=auth_header(token),
        json={"show_reviews_count": False},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["show_reviews_count"] is False
    assert body["show_purchases_count"] is True
    assert body["maintenance_mode"] is False
    assert settings_repository.values == {"show_reviews_count": False}

    audit = repository.audit_logs[-1]
    assert audit.action is AdminAuditAction.SETTINGS_UPDATED
    assert audit.admin_id == actor.id
    assert audit.target_key == "show_reviews_count"
    assert audit.old_value is True
    assert audit.new_value is False

    admin_read = await settings_client.get(
        "/api/v1/admin/settings",
        headers=auth_header(token),
    )
    assert admin_read.status_code == 200
    assert admin_read.json() == body


async def test_unknown_setting_key_is_rejected(
    settings_client: AsyncClient,
    repository: InMemoryAdminRepository,
    settings_repository: InMemorySettingsRepository,
) -> None:
    await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)
    token = await login(settings_client, "admin@prebook.io")

    response = await settings_client.patch(
        "/api/v1/admin/settings",
        headers=auth_header(token),
        json={"maintenance_mode": True, "unknown_key": "value"},
    )

    assert response.status_code == 422
    assert settings_repository.values == {}


async def test_empty_update_is_rejected(
    settings_client: AsyncClient,
    repository: InMemoryAdminRepository,
) -> None:
    await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)
    token = await login(settings_client, "admin@prebook.io")

    response = await settings_client.patch(
        "/api/v1/admin/settings",
        headers=auth_header(token),
        json={},
    )

    assert response.status_code == 422


async def test_settings_cache_is_used_and_invalidated(
    repository: InMemoryAdminRepository,
    settings_repository: InMemorySettingsRepository,
) -> None:
    actor = await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)
    service = SettingsService(
        cast(SettingsRepository, settings_repository),
        cast(AdminRepository, repository),
    )

    first = await service.get_settings()
    second = await service.get_settings()

    assert first == SiteSettings()
    assert second == SiteSettings()
    assert settings_repository.load_count == 1
    assert settings_repository.cached is not None

    await service.update_settings(
        actor,
        SiteSettingsUpdate(show_purchases_count=False),
        None,
    )

    assert settings_repository.invalidate_count == 1
    assert settings_repository.cached is not None
    assert settings_repository.cached["show_purchases_count"] is False

    third = await service.get_settings()
    assert third.show_purchases_count is False
    assert settings_repository.load_count == 1


async def test_public_settings_etag_returns_not_modified(settings_client: AsyncClient) -> None:
    first = await settings_client.get("/api/v1/public/settings")
    etag = first.headers["etag"]

    not_modified = await settings_client.get(
        "/api/v1/public/settings",
        headers={"If-None-Match": etag},
    )
    stale = await settings_client.get(
        "/api/v1/public/settings",
        headers={"If-None-Match": '"stale"'},
    )

    assert not_modified.status_code == 304
    assert not_modified.headers["etag"] == etag
    assert not_modified.headers["cache-control"] == "public, max-age=30"
    assert not_modified.content == b""
    assert stale.status_code == 200


async def test_maintenance_blocks_public_routes_and_keeps_exempt_routes(
    settings_client: AsyncClient,
    repository: InMemoryAdminRepository,
    settings_repository: InMemorySettingsRepository,
) -> None:
    settings_repository.values["maintenance_mode"] = True
    settings_repository.values["maintenance_message"] = "Retour imminent."
    await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)
    token = await login(settings_client, "admin@prebook.io")

    blocked = await settings_client.get("/api/v1/catalog")
    public_settings = await settings_client.get("/api/v1/public/settings")
    login_attempt = await settings_client.post(
        "/api/v1/auth/login",
        json={"email": "unknown@prebook.io", "password": PASSWORD},
    )
    admin_settings = await settings_client.get(
        "/api/v1/admin/settings",
        headers=auth_header(token),
    )

    assert blocked.status_code == 503
    assert blocked.headers["retry-after"] == "3600"
    assert blocked.json()["error"]["code"] == "maintenance"
    assert blocked.json()["error"]["message"] == "Retour imminent."
    assert public_settings.status_code == 200
    assert login_attempt.status_code == 401
    assert admin_settings.status_code == 200
    assert admin_settings.json()["maintenance_mode"] is True


async def test_health_route_is_exempt_from_maintenance(
    app: FastAPI,
    settings_client: AsyncClient,
    settings_repository: InMemorySettingsRepository,
) -> None:
    app.dependency_overrides[get_health_service] = HealthyService
    settings_repository.values["maintenance_mode"] = True

    response = await settings_client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_settings_admin_routes_require_admin_rights(
    settings_client: AsyncClient,
    repository: InMemoryAdminRepository,
) -> None:
    customer = await seed_user(repository, "customer@prebook.io", UserRole.CUSTOMER)
    customer_token = create_token_pair(str(customer.id), {"role": customer.role.value})

    anonymous = await settings_client.get("/api/v1/admin/settings")
    forbidden = await settings_client.patch(
        "/api/v1/admin/settings",
        headers=auth_header(customer_token.access_token),
        json={"maintenance_mode": True},
    )

    assert anonymous.status_code == 401
    assert forbidden.status_code == 403


async def test_optional_counts_skip_disabled_queries(
    repository: InMemoryAdminRepository,
    settings_repository: InMemorySettingsRepository,
) -> None:
    actor = await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)
    service = SettingsService(
        cast(SettingsRepository, settings_repository),
        cast(AdminRepository, repository),
    )
    await service.update_settings(
        actor,
        SiteSettingsUpdate(show_reviews_count=False),
        None,
    )
    calls = {"reviews": 0, "purchases": 0}

    async def review_counter() -> int:
        calls["reviews"] += 1
        return 4

    async def purchase_counter() -> int:
        calls["purchases"] += 1
        return 2

    counts = await service.resolve_optional_counts(review_counter, purchase_counter)

    assert counts.reviews_count is None
    assert counts.purchases_count == 2
    assert calls == {"reviews": 0, "purchases": 1}
