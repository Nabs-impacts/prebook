from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from app.core.security import create_token_pair
from app.models.enums import AdminAuditAction, OrderStatus, UserRole
from app.services.order import OrderService
from app.services.payment_provider import FakePaymentProvider, ProviderPaymentStatus
from httpx import AsyncClient

from tests.conftest import TEST_FAKE_WEBHOOK_SECRET
from tests.support import InMemoryAdminRepository, seed_user
from tests.support_catalog import InMemoryEbookRepository, InMemoryOrderRepository
from tests.support_order import FakeTaskQueue, order_payload, seed_ebook

PASSWORD = "Password123!"


async def login(client: AsyncClient, email: str) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 200
    return str(response.json()["access_token"])


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def create_order(
    client: AsyncClient,
    *,
    email: str = "buyer@example.com",
    slug: str = "guide-prebook",
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
    response = await client.post(
        "/api/v1/orders",
        json=order_payload(slug=slug, email=email),
        headers=headers,
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


async def send_webhook(
    client: AsyncClient,
    reference: str,
    *,
    provider: str = "fake",
    status_value: str = "succeeded",
    secret: str = TEST_FAKE_WEBHOOK_SECRET,
) -> Any:
    return await client.post(
        f"/api/v1/webhooks/payments/{provider}",
        json={"reference": reference, "status": status_value},
        headers={"Secret-Hash": secret},
    )


def fake_reference(public_id: str) -> str:
    return f"fake_{public_id}"


async def test_create_order_uses_server_price(
    order_client: AsyncClient,
    ebook_repository: InMemoryEbookRepository,
    fake_payment_provider: FakePaymentProvider,
) -> None:
    ebook = await seed_ebook(ebook_repository, price=7500)

    body = await create_order(order_client)

    assert body["amount"] == ebook.price == 7500
    assert body["currency"] == "XOF"
    assert body["status"] == "pending"
    assert body["provider"] == "fake"
    assert body["payment_url"] == (
        f"https://fake-payments.test/checkout/{fake_reference(body['public_id'])}"
    )
    assert body["payment_expires_at"] is not None
    assert "payment_method" not in body
    assert fake_payment_provider is not None


async def test_create_order_rejects_client_price(
    order_client: AsyncClient,
    ebook_repository: InMemoryEbookRepository,
) -> None:
    ebook = await seed_ebook(ebook_repository, price=7500)
    payload = order_payload()
    payload["amount"] = "1"

    response = await order_client.post("/api/v1/orders", json=payload)

    assert response.status_code == 422
    assert ebook.price == 7500


async def test_create_order_unknown_ebook(
    order_client: AsyncClient,
) -> None:
    response = await order_client.post(
        "/api/v1/orders",
        json=order_payload(slug="inconnu"),
    )

    assert response.status_code == 404


async def test_payment_method_is_optional_and_ignored(
    order_client: AsyncClient,
    ebook_repository: InMemoryEbookRepository,
) -> None:
    await seed_ebook(ebook_repository)
    payload = order_payload()
    payload["payment_method"] = "mynita"

    response = await order_client.post("/api/v1/orders", json=payload)

    assert response.status_code == 201
    assert response.json()["provider"] == "fake"


async def test_payments_disabled_rejects_creation(
    order_client: AsyncClient,
    ebook_repository: InMemoryEbookRepository,
    repository: InMemoryAdminRepository,
) -> None:
    await seed_ebook(ebook_repository)
    await seed_user(repository, "admin@example.com", UserRole.ADMIN)
    token = await login(order_client, "admin@example.com")

    update = await order_client.patch(
        "/api/v1/admin/settings",
        headers=auth_header(token),
        json={"payments_enabled": False},
    )
    assert update.status_code == 200

    response = await order_client.post("/api/v1/orders", json=order_payload())

    assert response.status_code == 400


async def test_idempotency_key_reuses_order(
    order_client: AsyncClient,
    ebook_repository: InMemoryEbookRepository,
    order_repository: InMemoryOrderRepository,
    fake_payment_provider: FakePaymentProvider,
) -> None:
    await seed_ebook(ebook_repository)

    first = await create_order(order_client, idempotency_key="cle-123")
    second = await create_order(order_client, idempotency_key="cle-123")

    assert first["public_id"] == second["public_id"]
    assert len(order_repository.orders) == 1
    assert fake_payment_provider is not None


async def test_webhook_valid_marks_paid_and_enqueues(
    order_client: AsyncClient,
    ebook_repository: InMemoryEbookRepository,
    fake_payment_provider: FakePaymentProvider,
    fake_task_queue: FakeTaskQueue,
) -> None:
    await seed_ebook(ebook_repository)
    order = await create_order(order_client)
    reference = fake_reference(order["public_id"])
    fake_payment_provider.set_status(reference, ProviderPaymentStatus.SUCCEEDED)

    response = await send_webhook(order_client, reference)

    assert response.status_code == 204
    status_response = await order_client.get(f"/api/v1/orders/{order['public_id']}/status")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "paid"
    assert status_response.json()["paid_at"] is not None
    assert fake_task_queue.fulfilled == [UUID(order["public_id"])]


async def test_webhook_invalid_signature_is_rejected(
    order_client: AsyncClient,
    ebook_repository: InMemoryEbookRepository,
) -> None:
    await seed_ebook(ebook_repository)
    order = await create_order(order_client)
    reference = fake_reference(order["public_id"])

    response = await send_webhook(order_client, reference, secret="mauvais-secret")

    assert response.status_code == 403
    status_response = await order_client.get(f"/api/v1/orders/{order['public_id']}/status")
    assert status_response.json()["status"] == "pending"


async def test_webhook_replay_is_idempotent(
    order_client: AsyncClient,
    ebook_repository: InMemoryEbookRepository,
    fake_payment_provider: FakePaymentProvider,
    fake_task_queue: FakeTaskQueue,
) -> None:
    await seed_ebook(ebook_repository)
    order = await create_order(order_client)
    reference = fake_reference(order["public_id"])
    fake_payment_provider.set_status(reference, ProviderPaymentStatus.SUCCEEDED)

    first = await send_webhook(order_client, reference)
    first_status = await order_client.get(f"/api/v1/orders/{order['public_id']}/status")
    second = await send_webhook(order_client, reference)
    second_status = await order_client.get(f"/api/v1/orders/{order['public_id']}/status")

    assert first.status_code == 204
    assert second.status_code == 204
    assert first_status.json()["paid_at"] == second_status.json()["paid_at"]
    assert len(fake_task_queue.fulfilled) == 1


async def test_webhook_does_not_trust_payload_status(
    order_client: AsyncClient,
    ebook_repository: InMemoryEbookRepository,
    fake_payment_provider: FakePaymentProvider,
) -> None:
    await seed_ebook(ebook_repository)
    order = await create_order(order_client)
    reference = fake_reference(order["public_id"])

    await send_webhook(order_client, reference, status_value="succeeded")
    pending_status = await order_client.get(f"/api/v1/orders/{order['public_id']}/status")
    assert pending_status.json()["status"] == "pending"

    fake_payment_provider.set_status(reference, ProviderPaymentStatus.SUCCEEDED)
    await send_webhook(order_client, reference, status_value="failed")
    paid_status = await order_client.get(f"/api/v1/orders/{order['public_id']}/status")
    assert paid_status.json()["status"] == "paid"


async def test_webhook_failed_keeps_order_pending(
    order_client: AsyncClient,
    ebook_repository: InMemoryEbookRepository,
    order_repository: InMemoryOrderRepository,
    fake_payment_provider: FakePaymentProvider,
) -> None:
    await seed_ebook(ebook_repository)
    order = await create_order(order_client)
    reference = fake_reference(order["public_id"])
    fake_payment_provider.set_status(reference, ProviderPaymentStatus.FAILED)

    response = await send_webhook(
        order_client,
        reference,
        status_value="failed",
    )

    assert response.status_code == 204
    stored = order_repository.orders[UUID(order["public_id"])]
    assert stored.status is OrderStatus.PENDING
    assert stored.payment_failure_reason is None


async def test_webhook_out_of_order_does_not_revert_paid(
    order_client: AsyncClient,
    ebook_repository: InMemoryEbookRepository,
    fake_payment_provider: FakePaymentProvider,
) -> None:
    await seed_ebook(ebook_repository)
    order = await create_order(order_client)
    reference = fake_reference(order["public_id"])

    fake_payment_provider.set_status(reference, ProviderPaymentStatus.SUCCEEDED)
    await send_webhook(order_client, reference)
    await send_webhook(order_client, reference, status_value="failed")

    status_response = await order_client.get(f"/api/v1/orders/{order['public_id']}/status")
    assert status_response.json()["status"] == "paid"


async def test_refund_is_allowed_from_paid(
    order_client: AsyncClient,
    ebook_repository: InMemoryEbookRepository,
    fake_payment_provider: FakePaymentProvider,
) -> None:
    await seed_ebook(ebook_repository)
    order = await create_order(order_client)
    reference = fake_reference(order["public_id"])

    fake_payment_provider.set_status(reference, ProviderPaymentStatus.SUCCEEDED)
    await send_webhook(order_client, reference)
    fake_payment_provider.set_status(reference, ProviderPaymentStatus.REFUNDED)
    response = await send_webhook(order_client, reference, status_value="refunded")

    assert response.status_code == 204
    status_response = await order_client.get(f"/api/v1/orders/{order['public_id']}/status")
    assert status_response.json()["status"] == "refunded"


async def test_reconciliation_updates_pending_order(
    order_client: AsyncClient,
    ebook_repository: InMemoryEbookRepository,
    order_repository: InMemoryOrderRepository,
    fake_payment_provider: FakePaymentProvider,
    fake_task_queue: FakeTaskQueue,
    order_service: OrderService,
) -> None:
    await seed_ebook(ebook_repository)
    order = await create_order(order_client)
    reference = fake_reference(order["public_id"])
    fake_payment_provider.set_status(reference, ProviderPaymentStatus.SUCCEEDED)
    stored = order_repository.orders[UUID(order["public_id"])]
    stored.created_at = datetime.now(UTC) - timedelta(minutes=6)

    changed = await order_service.reconcile_payment_orders()

    assert changed == 1
    assert stored.status is OrderStatus.PAID
    assert fake_task_queue.fulfilled == [stored.id]


async def test_reconciliation_marks_expired_then_final_check_fails(
    order_client: AsyncClient,
    ebook_repository: InMemoryEbookRepository,
    order_repository: InMemoryOrderRepository,
    fake_payment_provider: FakePaymentProvider,
    order_service: OrderService,
) -> None:
    await seed_ebook(ebook_repository)
    order = await create_order(order_client)
    reference = fake_reference(order["public_id"])
    fake_payment_provider.set_status(reference, ProviderPaymentStatus.CANCELLED)
    stored = order_repository.orders[UUID(order["public_id"])]
    stored.created_at = datetime.now(UTC) - timedelta(minutes=6)

    await order_service.reconcile_payment_orders()
    assert stored.status.value == "expired"

    await order_service.reconcile_payment_orders()
    assert stored.status.value == "failed"


async def test_reconciliation_marks_expired_then_late_payment(
    order_client: AsyncClient,
    ebook_repository: InMemoryEbookRepository,
    order_repository: InMemoryOrderRepository,
    fake_payment_provider: FakePaymentProvider,
    order_service: OrderService,
) -> None:
    await seed_ebook(ebook_repository)
    order = await create_order(order_client)
    reference = fake_reference(order["public_id"])
    fake_payment_provider.set_status(reference, ProviderPaymentStatus.CANCELLED)
    stored = order_repository.orders[UUID(order["public_id"])]
    stored.created_at = datetime.now(UTC) - timedelta(minutes=6)

    await order_service.reconcile_payment_orders()
    assert stored.status.value == "expired"

    fake_payment_provider.set_status(reference, ProviderPaymentStatus.SUCCEEDED)
    await order_service.reconcile_payment_orders()
    assert stored.status.value == "paid"


async def test_order_rate_limit(
    order_client: AsyncClient,
    ebook_repository: InMemoryEbookRepository,
) -> None:
    await seed_ebook(ebook_repository)

    statuses = []
    for _ in range(6):
        response = await order_client.post("/api/v1/orders", json=order_payload())
        statuses.append(response.status_code)

    assert statuses[:5] == [201] * 5
    assert statuses[5] == 429


async def test_admin_orders_requires_admin(
    order_client: AsyncClient,
    repository: InMemoryAdminRepository,
) -> None:
    customer = await seed_user(repository, "client@example.com", UserRole.CUSTOMER)
    pair = create_token_pair(str(customer.id), {"role": customer.role.value})

    anonymous = await order_client.get("/api/v1/admin/orders")
    forbidden = await order_client.get(
        "/api/v1/admin/orders",
        headers=auth_header(pair.access_token),
    )

    assert anonymous.status_code == 401
    assert forbidden.status_code == 403


async def test_admin_orders_filters_and_detail(
    order_client: AsyncClient,
    ebook_repository: InMemoryEbookRepository,
    repository: InMemoryAdminRepository,
    fake_payment_provider: FakePaymentProvider,
) -> None:
    ebook = await seed_ebook(ebook_repository)
    other = await seed_ebook(ebook_repository, slug="autre", title="Autre", price=3000)
    await seed_user(repository, "admin@example.com", UserRole.ADMIN)
    token = await login(order_client, "admin@example.com")

    paid_order = await create_order(order_client, email="alice@example.com")
    pending_order = await create_order(order_client, email="bob@example.com", slug=other.slug)
    reference = fake_reference(paid_order["public_id"])
    fake_payment_provider.set_status(reference, ProviderPaymentStatus.SUCCEEDED)
    await send_webhook(order_client, reference)

    headers = auth_header(token)
    paid = await order_client.get(
        "/api/v1/admin/orders",
        headers=headers,
        params={"status": "paid"},
    )
    assert paid.status_code == 200
    assert paid.json()["total"] == 1
    assert paid.json()["items"][0]["id"] == paid_order["public_id"]

    searched = await order_client.get(
        "/api/v1/admin/orders",
        headers=headers,
        params={"email": "bob@"},
    )
    assert searched.json()["total"] == 1
    assert searched.json()["items"][0]["id"] == pending_order["public_id"]

    by_ebook = await order_client.get(
        "/api/v1/admin/orders",
        headers=headers,
        params={"ebook_id": str(ebook.id)},
    )
    assert by_ebook.json()["total"] == 1

    detail = await order_client.get(
        f"/api/v1/admin/orders/{paid_order['public_id']}",
        headers=headers,
    )
    assert detail.status_code == 200
    assert detail.json()["ebook_title"] == ebook.title
    assert detail.json()["buyer_email"] == "alice@example.com"


async def test_admin_can_refund_order_with_audit(
    order_client: AsyncClient,
    ebook_repository: InMemoryEbookRepository,
    repository: InMemoryAdminRepository,
    fake_payment_provider: FakePaymentProvider,
) -> None:
    await seed_ebook(ebook_repository)
    actor = await seed_user(repository, "admin@example.com", UserRole.ADMIN)
    token = await login(order_client, "admin@example.com")
    order = await create_order(order_client)
    reference = fake_reference(order["public_id"])
    fake_payment_provider.set_status(reference, ProviderPaymentStatus.SUCCEEDED)
    await send_webhook(order_client, reference)

    response = await order_client.post(
        f"/api/v1/admin/orders/{order['public_id']}/refund",
        headers=auth_header(token),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "refunded"
    assert repository.audit_logs[-1].action is AdminAuditAction.ORDER_REFUNDED
    assert repository.audit_logs[-1].admin_id == actor.id


async def test_admin_can_recheck_order_with_audit(
    order_client: AsyncClient,
    ebook_repository: InMemoryEbookRepository,
    repository: InMemoryAdminRepository,
    fake_payment_provider: FakePaymentProvider,
) -> None:
    await seed_ebook(ebook_repository)
    actor = await seed_user(repository, "admin@example.com", UserRole.ADMIN)
    token = await login(order_client, "admin@example.com")
    order = await create_order(order_client)
    reference = fake_reference(order["public_id"])
    fake_payment_provider.set_status(reference, ProviderPaymentStatus.SUCCEEDED)

    response = await order_client.post(
        f"/api/v1/admin/orders/{order['public_id']}/recheck",
        headers=auth_header(token),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "paid"
    assert repository.audit_logs[-1].action is AdminAuditAction.ORDER_RECHECKED
    assert repository.audit_logs[-1].admin_id == actor.id
