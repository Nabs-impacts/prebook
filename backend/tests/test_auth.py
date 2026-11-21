from typing import cast

import pytest
from app.core.security import create_token_pair, hash_token
from app.models.enums import AdminAuditAction, UserRole
from fakeredis.aioredis import FakeRedis
from httpx import AsyncClient

from tests.support import InMemoryAdminRepository, TokenBody, seed_user

PASSWORD = "Password123!"


async def login(client: AsyncClient, email: str, password: str = PASSWORD) -> TokenBody:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    return cast(TokenBody, response.json())


async def test_login_success_returns_tokens_and_audits(
    auth_client: AsyncClient,
    repository: InMemoryAdminRepository,
    fake_redis: FakeRedis,
) -> None:
    user = await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)

    body = await login(auth_client, "admin@prebook.io")

    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 900
    assert repository.audit_logs[-1].action is AdminAuditAction.LOGIN
    assert repository.audit_logs[-1].admin_id == user.id
    stored_keys = await fake_redis.keys("auth:refresh:*")
    assert f"auth:refresh:{hash_token(body['refresh_token'])}" in stored_keys
    assert body["refresh_token"] not in stored_keys

    response = await auth_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert response.status_code == 200
    assert response.json()["email"] == "admin@prebook.io"
    assert response.json()["role"] == "admin"


async def test_login_failure_is_generic(
    auth_client: AsyncClient, repository: InMemoryAdminRepository
) -> None:
    await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)

    wrong_password = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@prebook.io", "password": "WrongPassword!"},
    )
    unknown_email = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "unknown@prebook.io", "password": PASSWORD},
    )

    assert wrong_password.status_code == 401
    assert unknown_email.status_code == 401
    assert (
        wrong_password.json()["error"]["message"]
        == unknown_email.json()["error"]["message"]
        == "Email ou mot de passe incorrect."
    )


async def test_inactive_admin_cannot_login(
    auth_client: AsyncClient, repository: InMemoryAdminRepository
) -> None:
    await seed_user(
        repository,
        "inactive@prebook.io",
        UserRole.ADMIN,
        is_active=False,
    )

    response = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "inactive@prebook.io", "password": PASSWORD},
    )

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Email ou mot de passe incorrect."


async def test_login_rate_limit_returns_429(
    auth_client: AsyncClient, repository: InMemoryAdminRepository
) -> None:
    await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)

    for _ in range(5):
        response = await auth_client.post(
            "/api/v1/auth/login",
            json={"email": "admin@prebook.io", "password": "WrongPassword!"},
        )
        assert response.status_code == 401

    blocked = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@prebook.io", "password": "WrongPassword!"},
    )

    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "too_many_requests"


async def test_refresh_rotates_and_rejects_reuse(
    auth_client: AsyncClient,
    repository: InMemoryAdminRepository,
) -> None:
    await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)
    tokens = await login(auth_client, "admin@prebook.io")

    refreshed = await auth_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refreshed.status_code == 200
    new_tokens = refreshed.json()
    assert new_tokens["refresh_token"] != tokens["refresh_token"]

    reused = await auth_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert reused.status_code == 401

    second_refresh = await auth_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": new_tokens["refresh_token"]},
    )
    assert second_refresh.status_code == 200


async def test_logout_revokes_access_and_refresh_tokens(
    auth_client: AsyncClient,
    repository: InMemoryAdminRepository,
) -> None:
    await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)
    tokens = await login(auth_client, "admin@prebook.io")

    response = await auth_client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert response.status_code == 204

    me = await auth_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert me.status_code == 401

    refresh = await auth_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refresh.status_code == 401


async def test_customer_token_is_forbidden_on_admin_routes(
    auth_client: AsyncClient,
    repository: InMemoryAdminRepository,
) -> None:
    customer = await seed_user(repository, "customer@prebook.io", UserRole.CUSTOMER)
    tokens = create_token_pair(str(customer.id), {"role": customer.role.value})

    response = await auth_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens.access_token}"},
    )

    assert response.status_code == 403


@pytest.mark.parametrize("missing_header", [None, "Basic abc", "Bearer"])
async def test_admin_routes_require_bearer_token(
    auth_client: AsyncClient,
    missing_header: str | None,
) -> None:
    headers = {} if missing_header is None else {"Authorization": missing_header}

    response = await auth_client.get("/api/v1/auth/me", headers=headers)

    assert response.status_code == 401
