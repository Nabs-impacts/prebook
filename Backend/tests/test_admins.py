from typing import cast
from uuid import uuid4

import pytest
from app.core.errors import ConflictError
from app.models.enums import AdminAuditAction, UserRole
from app.repositories.admin import AdminRepository
from app.repositories.token import TokenRepository
from app.schemas.admin import AdminUpdate
from app.services.admin import (
    LAST_SUPER_ADMIN_MESSAGE,
    SELF_DEACTIVATE_MESSAGE,
    SELF_DELETE_MESSAGE,
    AdminService,
)
from fakeredis.aioredis import FakeRedis
from httpx import AsyncClient
from redis.asyncio import Redis

from tests.support import InMemoryAdminRepository, TokenBody, build_user, seed_user

PASSWORD = "Password123!"
NEW_PASSWORD = "NewPassword123!"


async def login(client: AsyncClient, email: str, password: str = PASSWORD) -> TokenBody:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    return cast(TokenBody, response.json())


def auth_header(tokens: TokenBody) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def test_super_admin_manages_admins_and_writes_audit(
    auth_client: AsyncClient,
    repository: InMemoryAdminRepository,
) -> None:
    actor = await seed_user(repository, "super@prebook.io", UserRole.SUPER_ADMIN)
    tokens = await login(auth_client, "super@prebook.io")

    created = await auth_client.post(
        "/api/v1/admin/admins",
        headers=auth_header(tokens),
        json={"email": "new@prebook.io", "password": PASSWORD, "role": "admin"},
    )
    assert created.status_code == 201
    created_body = created.json()
    assert created_body["email"] == "new@prebook.io"
    assert created_body["role"] == "admin"
    created_audit = repository.audit_logs[-1]
    assert created_audit.action is AdminAuditAction.ADMIN_CREATED
    assert created_audit.admin_id == actor.id
    assert str(created_audit.target_id) == created_body["id"]

    listed = await auth_client.get("/api/v1/admin/admins", headers=auth_header(tokens))
    assert listed.status_code == 200
    assert listed.json()["total"] == 2

    target_id = created_body["id"]
    updated = await auth_client.patch(
        f"/api/v1/admin/admins/{target_id}",
        headers=auth_header(tokens),
        json={"is_active": False},
    )
    assert updated.status_code == 200
    assert updated.json()["is_active"] is False
    updated_audit = repository.audit_logs[-1]
    assert updated_audit.action is AdminAuditAction.ADMIN_UPDATED

    deleted = await auth_client.delete(
        f"/api/v1/admin/admins/{target_id}",
        headers=auth_header(tokens),
    )
    assert deleted.status_code == 204
    deleted_audit = repository.audit_logs[-1]
    assert deleted_audit.action is AdminAuditAction.ADMIN_DELETED
    assert str(deleted_audit.target_id) == target_id


async def test_simple_admin_is_forbidden_on_admin_management(
    auth_client: AsyncClient,
    repository: InMemoryAdminRepository,
) -> None:
    admin = await seed_user(repository, "admin@prebook.io", UserRole.ADMIN)
    await seed_user(repository, "super@prebook.io", UserRole.SUPER_ADMIN)
    tokens = await login(auth_client, "admin@prebook.io")
    target_id = uuid4()

    me = await auth_client.get("/api/v1/auth/me", headers=auth_header(tokens))
    listed = await auth_client.get("/api/v1/admin/admins", headers=auth_header(tokens))
    created = await auth_client.post(
        "/api/v1/admin/admins",
        headers=auth_header(tokens),
        json={"email": "other@prebook.io", "password": PASSWORD, "role": "admin"},
    )
    updated = await auth_client.patch(
        f"/api/v1/admin/admins/{target_id}",
        headers=auth_header(tokens),
        json={"is_active": False},
    )
    deleted = await auth_client.delete(
        f"/api/v1/admin/admins/{target_id}",
        headers=auth_header(tokens),
    )

    assert me.status_code == 200
    assert me.json()["id"] == str(admin.id)
    assert listed.status_code == 403
    assert created.status_code == 403
    assert updated.status_code == 403
    assert deleted.status_code == 403


async def test_duplicate_admin_email_is_rejected(
    auth_client: AsyncClient,
    repository: InMemoryAdminRepository,
) -> None:
    await seed_user(repository, "super@prebook.io", UserRole.SUPER_ADMIN)
    await seed_user(repository, "existing@prebook.io", UserRole.ADMIN)
    tokens = await login(auth_client, "super@prebook.io")

    response = await auth_client.post(
        "/api/v1/admin/admins",
        headers=auth_header(tokens),
        json={"email": "existing@prebook.io", "password": PASSWORD, "role": "admin"},
    )

    assert response.status_code == 409


async def test_admin_password_change_revokes_refresh_and_updates_hash(
    auth_client: AsyncClient,
    repository: InMemoryAdminRepository,
) -> None:
    await seed_user(repository, "super@prebook.io", UserRole.SUPER_ADMIN)
    target = await seed_user(repository, "target@prebook.io", UserRole.ADMIN)
    actor_tokens = await login(auth_client, "super@prebook.io")
    target_tokens = await login(auth_client, "target@prebook.io")

    response = await auth_client.patch(
        f"/api/v1/admin/admins/{target.id}",
        headers=auth_header(actor_tokens),
        json={"password": NEW_PASSWORD},
    )
    assert response.status_code == 200

    old_refresh = await auth_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": target_tokens["refresh_token"]},
    )
    old_login = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "target@prebook.io", "password": PASSWORD},
    )
    new_login = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "target@prebook.io", "password": NEW_PASSWORD},
    )

    assert old_refresh.status_code == 401
    assert old_login.status_code == 401
    assert new_login.status_code == 200


async def test_deactivation_revokes_refresh_and_blocks_login(
    auth_client: AsyncClient,
    repository: InMemoryAdminRepository,
) -> None:
    await seed_user(repository, "super@prebook.io", UserRole.SUPER_ADMIN)
    target = await seed_user(repository, "target@prebook.io", UserRole.ADMIN)
    actor_tokens = await login(auth_client, "super@prebook.io")
    target_tokens = await login(auth_client, "target@prebook.io")

    response = await auth_client.patch(
        f"/api/v1/admin/admins/{target.id}",
        headers=auth_header(actor_tokens),
        json={"is_active": False},
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    refresh = await auth_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": target_tokens["refresh_token"]},
    )
    login_attempt = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "target@prebook.io", "password": PASSWORD},
    )

    assert refresh.status_code == 401
    assert login_attempt.status_code == 401


async def test_super_admin_cannot_delete_or_deactivate_self(
    auth_client: AsyncClient,
    repository: InMemoryAdminRepository,
) -> None:
    actor = await seed_user(repository, "super@prebook.io", UserRole.SUPER_ADMIN)
    tokens = await login(auth_client, "super@prebook.io")

    deactivated = await auth_client.patch(
        f"/api/v1/admin/admins/{actor.id}",
        headers=auth_header(tokens),
        json={"is_active": False},
    )
    deleted = await auth_client.delete(
        f"/api/v1/admin/admins/{actor.id}",
        headers=auth_header(tokens),
    )

    assert deactivated.status_code == 409
    assert deactivated.json()["error"]["message"] == SELF_DEACTIVATE_MESSAGE
    assert deleted.status_code == 409
    assert deleted.json()["error"]["message"] == SELF_DELETE_MESSAGE


async def test_second_super_admin_can_be_deleted(
    auth_client: AsyncClient,
    repository: InMemoryAdminRepository,
) -> None:
    await seed_user(repository, "super@prebook.io", UserRole.SUPER_ADMIN)
    other = await seed_user(repository, "other-super@prebook.io", UserRole.SUPER_ADMIN)
    tokens = await login(auth_client, "super@prebook.io")

    response = await auth_client.delete(
        f"/api/v1/admin/admins/{other.id}",
        headers=auth_header(tokens),
    )
    listed = await auth_client.get("/api/v1/admin/admins", headers=auth_header(tokens))

    assert response.status_code == 204
    assert listed.json()["total"] == 1


async def test_last_super_admin_is_protected(
    repository: InMemoryAdminRepository,
    fake_redis: FakeRedis,
) -> None:
    target = await seed_user(repository, "last@prebook.io", UserRole.SUPER_ADMIN)
    actor = build_user("actor@prebook.io", UserRole.SUPER_ADMIN)
    actor.id = uuid4()
    service = AdminService(
        cast(AdminRepository, repository),
        TokenRepository(cast(Redis, fake_redis)),
    )

    with pytest.raises(ConflictError, match=LAST_SUPER_ADMIN_MESSAGE):
        await service.delete_admin(actor, target.id, None)

    with pytest.raises(ConflictError, match=LAST_SUPER_ADMIN_MESSAGE):
        await service.update_admin(
            actor,
            target.id,
            AdminUpdate(is_active=False),
            None,
        )


async def test_missing_admin_returns_404(
    auth_client: AsyncClient,
    repository: InMemoryAdminRepository,
) -> None:
    await seed_user(repository, "super@prebook.io", UserRole.SUPER_ADMIN)
    tokens = await login(auth_client, "super@prebook.io")
    missing_id = uuid4()

    updated = await auth_client.patch(
        f"/api/v1/admin/admins/{missing_id}",
        headers=auth_header(tokens),
        json={"is_active": False},
    )
    deleted = await auth_client.delete(
        f"/api/v1/admin/admins/{missing_id}",
        headers=auth_header(tokens),
    )

    assert updated.status_code == 404
    assert deleted.status_code == 404


async def test_admin_list_is_paginated(
    auth_client: AsyncClient,
    repository: InMemoryAdminRepository,
) -> None:
    await seed_user(repository, "super@prebook.io", UserRole.SUPER_ADMIN)
    await seed_user(repository, "admin1@prebook.io", UserRole.ADMIN)
    await seed_user(repository, "admin2@prebook.io", UserRole.ADMIN)
    tokens = await login(auth_client, "super@prebook.io")

    first_page = await auth_client.get(
        "/api/v1/admin/admins",
        headers=auth_header(tokens),
        params={"page": 1, "page_size": 2},
    )
    second_page = await auth_client.get(
        "/api/v1/admin/admins",
        headers=auth_header(tokens),
        params={"page": 2, "page_size": 2},
    )

    assert first_page.status_code == 200
    assert first_page.json()["total"] == 3
    assert first_page.json()["pages"] == 2
    assert len(first_page.json()["items"]) == 2
    assert len(second_page.json()["items"]) == 1


async def test_customer_role_cannot_be_created(
    auth_client: AsyncClient,
    repository: InMemoryAdminRepository,
) -> None:
    await seed_user(repository, "super@prebook.io", UserRole.SUPER_ADMIN)
    tokens = await login(auth_client, "super@prebook.io")

    response = await auth_client.post(
        "/api/v1/admin/admins",
        headers=auth_header(tokens),
        json={"email": "customer@prebook.io", "password": PASSWORD, "role": "customer"},
    )

    assert response.status_code == 422
