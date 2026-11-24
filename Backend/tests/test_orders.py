from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

import pytest
from app.core.errors import ServiceUnavailableError
from app.core.security import create_token_pair
from app.models.enums import OrderStatus, UserRole
from app.services.order import OrderService
from app.services.payment_provider import FakePaymentProvider, IPayMoneyProvider
from httpx import AsyncClient
from starlette.requests import Request

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
    method: str = "fake",
    email: str = "buyer@example.com",
    slug: str = "guide-prebook",
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
    response = await client.post(
        "/api/v1/orders",
        json=order_payload(slug=slug, method=method, email=email),
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


def build_request(headers: dict[str, str]) -> Request:
    raw_headers = [(key.lower().encode(), value.encode()) for key, value in headers.items()]
    return Request({"type": "http", "headers": raw_headers})


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
    assert body["payment_method"] == "fake"
    assert body["provider"] == "fake"
    assert body["redirect_url"] == (
        f"https://fake-payments.test/checkout/{fake_reference(body['public_id'])}"
    )
    assert body["instructions"]
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
    fake_payment_provider.set_status(reference, OrderStatus.PAID)

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
    fake_payment_provider.set_status(reference, OrderStatus.PAID)

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

    fake_payment_provider.set_status(reference, OrderStatus.PAID)
    await send_webhook(order_client, reference, status_value="failed")
    paid_status = await order_client.get(f"/api/v1/orders/{order['public_id']}/status")
    assert paid_status.json()["status"] == "paid"


async def test_illegal_transition_is_refused(
    order_client: AsyncClient,
    ebook_repository: InMemoryEbookRepository,
    fake_payment_provider: FakePaymentProvider,
) -> None:
    await seed_ebook(ebook_repository)
    order = await create_order(order_client)
    reference = fake_reference(order["public_id"])

    fake_payment_provider.set_status(reference, OrderStatus.PAID)
    assert (await send_webhook(order_client, reference)).status_code == 204

    fake_payment_provider.set_status(reference, OrderStatus.FAILED)
    response = await send_webhook(order_client, reference)

    assert response.status_code == 409
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

    fake_payment_provider.set_status(reference, OrderStatus.PAID)
    await send_webhook(order_client, reference)
    fake_payment_provider.set_status(reference, OrderStatus.REFUNDED)
    response = await send_webhook(order_client, reference)

    assert response.status_code == 204
    status_response = await order_client.get(f"/api/v1/orders/{order['public_id']}/status")
    assert status_response.json()["status"] == "refunded"


async def test_expiration_fails_pending_order_after_provider_check(
    order_client: AsyncClient,
    ebook_repository: InMemoryEbookRepository,
    order_repository: InMemoryOrderRepository,
    fake_payment_provider: FakePaymentProvider,
    order_service: OrderService,
) -> None:
    await seed_ebook(ebook_repository)
    order = await create_order(order_client)
    stored = order_repository.orders[UUID(order["public_id"])]
    stored.created_at = datetime.now(UTC) - timedelta(minutes=31)

    changed = await order_service.expire_pending_orders()

    assert changed == 1
    assert stored.status is OrderStatus.FAILED
    assert fake_payment_provider is not None


async def test_expiration_marks_paid_when_provider_confirms(
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
    fake_payment_provider.set_status(reference, OrderStatus.PAID)
    stored = order_repository.orders[UUID(order["public_id"])]
    stored.created_at = datetime.now(UTC) - timedelta(minutes=31)

    changed = await order_service.expire_pending_orders()

    assert changed == 1
    assert stored.status is OrderStatus.PAID
    assert fake_task_queue.fulfilled == [stored.id]


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
    fake_payment_provider.set_status(reference, OrderStatus.PAID)
    stored = order_repository.orders[UUID(order["public_id"])]
    stored.created_at = datetime.now(UTC) - timedelta(minutes=6)

    changed = await order_service.reconcile_pending_orders()

    assert changed == 1
    assert stored.status is OrderStatus.PAID
    assert fake_task_queue.fulfilled == [stored.id]


async def test_reconciliation_leaves_pending_order_unchanged(
    order_client: AsyncClient,
    ebook_repository: InMemoryEbookRepository,
    order_repository: InMemoryOrderRepository,
    order_service: OrderService,
) -> None:
    await seed_ebook(ebook_repository)
    order = await create_order(order_client)
    stored = order_repository.orders[UUID(order["public_id"])]
    stored.created_at = datetime.now(UTC) - timedelta(minutes=6)

    changed = await order_service.reconcile_pending_orders()

    assert changed == 0
    assert stored.status is OrderStatus.PENDING


async def test_disabled_payment_method_is_rejected(
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
        json={"payment_mynita_enabled": False},
    )
    assert update.status_code == 200

    response = await order_client.post(
        "/api/v1/orders",
        json=order_payload(method="mynita"),
    )

    assert response.status_code == 400


async def test_unknown_payment_method_is_rejected(
    order_client: AsyncClient,
    ebook_repository: InMemoryEbookRepository,
) -> None:
    await seed_ebook(ebook_repository)

    response = await order_client.post(
        "/api/v1/orders",
        json=order_payload(method="inconnu"),
    )

    assert response.status_code == 400


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
    order_repository: InMemoryOrderRepository,
    repository: InMemoryAdminRepository,
    fake_payment_provider: FakePaymentProvider,
) -> None:
    ebook = await seed_ebook(ebook_repository)
    other = await seed_ebook(ebook_repository, slug="autre", title="Autre", price=3000)
    await seed_user(repository, "admin@example.com", UserRole.ADMIN)
    token = await login(order_client, "admin@example.com")

    paid_order = await create_order(
        order_client,
        email="alice@example.com",
    )
    pending_order = await create_order(
        order_client,
        email="bob@example.com",
        slug=other.slug,
    )
    reference = fake_reference(paid_order["public_id"])
    fake_payment_provider.set_status(reference, OrderStatus.PAID)
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

    stored = order_repository.orders[UUID(pending_order["public_id"])]
    stored.payment_method = "mynita"
    await order_repository.commit()
    by_method = await order_client.get(
        "/api/v1/admin/orders",
        headers=headers,
        params={"payment_method": "mynita"},
    )
    assert by_method.json()["total"] == 1
    assert by_method.json()["items"][0]["id"] == pending_order["public_id"]


async def test_ipay_webhook_uses_static_secret_hash() -> None:
    provider = IPayMoneyProvider(
        "pk",
        "sk",
        "https://api.i-pay.money",
        "sandbox",
        "secret-hash",
    )

    valid = build_request({"Secret-Hash": "secret-hash"})
    invalid = build_request({"Secret-Hash": "autre"})
    missing = build_request({})

    assert await provider.verify_webhook(valid) is True
    assert await provider.verify_webhook(invalid) is False
    assert await provider.verify_webhook(missing) is False
    assert provider.extract_reference({"data": {"reference": "ipay_ref"}}) == "ipay_ref"
    assert provider.extract_reference({"reference": "ipay_ref"}) is None


async def test_ipay_payment_operations_are_blocked_without_docs() -> None:
    provider = IPayMoneyProvider(None, None, "https://api.i-pay.money", "sandbox", None)

    with pytest.raises(ServiceUnavailableError):
        await provider.get_status("reference")
