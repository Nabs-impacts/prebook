import json
import logging
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from app.core.deps import (
    get_admin_service,
    get_auth_service,
    get_order_service,
    get_settings_service,
)
from app.models.enums import AdminAuditAction, OrderStatus
from app.models.order import Order
from app.repositories.admin import AdminRepository
from app.repositories.catalog_cache import CatalogCacheRepository
from app.repositories.ebook import EbookRepository
from app.repositories.login_attempt import LoginAttemptRepository
from app.repositories.order import OrderRepository
from app.repositories.order_rate_limit import OrderRateLimitRepository
from app.repositories.payment_state import PaymentStateRepository
from app.repositories.settings import SettingsRepository
from app.repositories.token import TokenRepository
from app.services.admin import AdminService
from app.services.auth import AuthService
from app.services.order import OrderService
from app.services.payment_provider import (
    IPayMoneyProvider,
    PaymentProviderRegistry,
    ProviderPaymentStatus,
)
from app.services.settings import SettingsService
from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI
from httpx import AsyncClient
from redis.asyncio import Redis

from tests.support import InMemoryAdminRepository, InMemorySettingsRepository
from tests.support_catalog import InMemoryEbookRepository, InMemoryOrderRepository
from tests.support_order import FakeTaskQueue, order_payload, seed_ebook

IPAY_WEBHOOK_SECRET = "ipay-webhook-secret"
FRONTEND_BASE_URL = "https://frontend.test"


class FakeIPayServer:
    def __init__(self) -> None:
        self.links: dict[str, dict[str, Any]] = {}
        self.transactions: dict[str, dict[str, Any]] = {}
        self.created: list[dict[str, Any]] = []
        self.requests: list[httpx.Request] = []

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "POST" and path.endswith("/external_payments"):
            return self._create(request)
        if request.method == "GET" and "/external_payments/" in path:
            return self._link(path.rsplit("/", 1)[-1])
        if request.method == "GET" and "/payments/" in path:
            return self._transaction(path.rsplit("/", 1)[-1])
        return httpx.Response(404, json={"message": "Not Found"})

    def _create(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        reference = str(body["reference"])
        self.created.append(body)
        self.links[reference] = {
            "status": "initiated",
            "amount": body["amount"],
            "reference": reference,
        }
        return httpx.Response(
            200,
            json={
                "title": body["title"],
                "amount": body["amount"],
                "reference": reference,
                "status": "initiated",
                "should_expire": True,
                "page_url": "https://pay.test/checkout",
            },
        )

    def _link(self, reference: str) -> httpx.Response:
        link = self.links.get(reference)
        if link is None:
            return httpx.Response(404, json={"message": "External payment not found"})
        if link.get("expired"):
            return httpx.Response(
                200,
                json={
                    "message": "Expired",
                    "has_expire": True,
                    "status": "cancelled",
                    "reference": reference,
                },
            )
        if link["status"] == "initiated":
            return httpx.Response(
                200,
                json={
                    "message": "Pending",
                    "status": "initiated",
                    "reference": reference,
                    "page_url": "https://pay.test/checkout",
                },
            )
        return httpx.Response(
            200,
            json={
                "reference": reference,
                "amount": link["amount"],
                "country": "NE",
                "currency": "XOF",
                "transaction_id": link.get("transaction_id", f"tx_{reference}"),
                "msisdn": "97000000",
                "customer_name": "Client Demo",
                "status": link["status"],
                "created_at": "2026-06-04T10:30:00.000Z",
            },
        )

    def _transaction(self, reference: str) -> httpx.Response:
        transaction = self.transactions.get(reference)
        if transaction is None:
            return httpx.Response(404, json={"message": "Payment Not Found"})
        return httpx.Response(200, json=transaction)

    def succeed_link(self, reference: str, amount: int | None = None) -> None:
        link = self.links[reference]
        link["status"] = "succeeded"
        if amount is not None:
            link["amount"] = amount

    def fail_link(self, reference: str) -> None:
        self.links[reference]["status"] = "failed"

    def expire_link(self, reference: str) -> None:
        self.links[reference]["expired"] = True

    def set_transaction(
        self,
        reference: str,
        *,
        status: str,
        amount: int,
        failure_reason: str | None = None,
    ) -> None:
        self.transactions[reference] = {
            "public_reference": reference,
            "external_reference": reference,
            "reference": reference,
            "status": status,
            "msisdn": "97000000",
            "amount": amount,
            "net_amount": amount,
            "failure_reason": failure_reason,
            "payment_method": "credit_card",
            "validated_at": "2026-06-04T10:30:00.000Z",
        }


@pytest.fixture
def ipay_server() -> FakeIPayServer:
    return FakeIPayServer()


@pytest.fixture
def ipay_provider(ipay_server: FakeIPayServer) -> IPayMoneyProvider:
    return IPayMoneyProvider(
        "sk_test",
        IPAY_WEBHOOK_SECRET,
        FRONTEND_BASE_URL,
        "sandbox",
        "https://i-pay.money/api/v1",
        transport=ipay_server.transport,
    )


@pytest.fixture
def ipay_registry(ipay_provider: IPayMoneyProvider) -> PaymentProviderRegistry:
    return PaymentProviderRegistry({"ipay_money": ipay_provider})


@pytest.fixture
def ipay_service(
    order_repository: InMemoryOrderRepository,
    ebook_repository: InMemoryEbookRepository,
    repository: InMemoryAdminRepository,
    settings_repository: InMemorySettingsRepository,
    fake_redis: FakeRedis,
    ipay_registry: PaymentProviderRegistry,
    fake_task_queue: FakeTaskQueue,
) -> OrderService:
    settings_service = SettingsService(
        cast(SettingsRepository, settings_repository),
        cast(AdminRepository, repository),
    )
    return OrderService(
        cast(OrderRepository, order_repository),
        cast(EbookRepository, ebook_repository),
        settings_service,
        ipay_registry,
        OrderRateLimitRepository(cast(Redis, fake_redis)),
        CatalogCacheRepository(cast(Redis, fake_redis)),
        fake_task_queue,
        cast(AdminRepository, repository),
        PaymentStateRepository(cast(Redis, fake_redis)),
        provider_code="ipay_money",
        rate_limit_attempts=100,
        rate_limit_window_seconds=60,
        reconciliation_max_age_minutes=120,
        reconciliation_interval_minutes=2,
        reconciliation_max_interval_minutes=30,
        task_batch_size=100,
    )


@pytest.fixture
async def ipay_client(
    app: FastAPI,
    repository: InMemoryAdminRepository,
    settings_repository: InMemorySettingsRepository,
    fake_redis: FakeRedis,
    ipay_service: OrderService,
) -> AsyncIterator[AsyncClient]:
    admin_repository = cast(AdminRepository, repository)
    token_repository = TokenRepository(cast(Redis, fake_redis))
    login_attempt_repository = LoginAttemptRepository(cast(Redis, fake_redis))
    settings_service = SettingsService(
        cast(SettingsRepository, settings_repository),
        admin_repository,
    )
    app.dependency_overrides[get_auth_service] = lambda: AuthService(
        admin_repository,
        token_repository,
        login_attempt_repository,
    )
    app.dependency_overrides[get_admin_service] = lambda: AdminService(
        admin_repository,
        token_repository,
    )
    app.dependency_overrides[get_settings_service] = lambda: settings_service
    app.dependency_overrides[get_order_service] = lambda: ipay_service
    app.state.maintenance_settings_provider = settings_service.get_settings

    transport = httpx.ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()
    app.state.maintenance_settings_provider = None


async def create_ipay_order(
    client: AsyncClient,
    *,
    email: str = "buyer@example.com",
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/orders",
        json=order_payload(email=email),
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


async def send_ipay_webhook(
    client: AsyncClient,
    *,
    order_reference: str,
    transaction_reference: str,
    status_value: str,
    amount: int,
    secret: str = IPAY_WEBHOOK_SECRET,
    failure_reason: str | None = None,
) -> Any:
    return await client.post(
        "/api/v1/webhooks/payments/ipay_money",
        json={
            "data": {
                "external_payment_reference": order_reference,
                "reference": transaction_reference,
                "status": status_value,
                "msisdn": "97000000",
                "net_amount": amount,
                "amount": amount,
                "failure_reason": failure_reason,
                "customer_name": "Client Demo",
                "payment_method": "credit_card",
                "validated_at": "2026-06-04T10:30:00.000Z",
            }
        },
        headers={"Secret-Hash": secret},
    )


async def test_create_payment_sends_hosted_link_request(
    ipay_client: AsyncClient,
    ipay_server: FakeIPayServer,
    ebook_repository: InMemoryEbookRepository,
    order_repository: InMemoryOrderRepository,
) -> None:
    ebook = await seed_ebook(ebook_repository, price=7500)

    body = await create_ipay_order(ipay_client)

    assert body["amount"] == ebook.price == 7500
    assert body["provider"] == "ipay_money"
    assert body["payment_url"] == "https://pay.test/checkout"
    request = ipay_server.requests[0]
    assert request.headers["Authorization"] == "Bearer sk_test"
    assert request.headers["Ipay-Target-Environment"] == "sandbox"
    assert request.headers["Ipay-Payment-Type"] == "external_payment"
    sent = ipay_server.created[0]
    assert sent["amount"] == 7500
    assert len(sent["reference"]) >= 32
    assert sent["shouldExpire"] is True
    assert sent["on_success_redirection_url"].startswith(
        f"{FRONTEND_BASE_URL}/orders/{body['public_id']}/success"
    )
    assert sent["on_failed_redirection_url"].startswith(
        f"{FRONTEND_BASE_URL}/orders/{body['public_id']}/failure"
    )
    stored = order_repository.orders[UUID(body["public_id"])]
    assert stored.provider_reference == sent["reference"]
    assert stored.payment_url == body["payment_url"]
    assert stored.payment_expires_at is not None


async def test_expired_link_is_recreated_on_status_read(
    ipay_client: AsyncClient,
    ipay_server: FakeIPayServer,
    ebook_repository: InMemoryEbookRepository,
    order_repository: InMemoryOrderRepository,
) -> None:
    await seed_ebook(ebook_repository)
    body = await create_ipay_order(ipay_client)
    stored = order_repository.orders[UUID(body["public_id"])]
    old_reference = stored.provider_reference
    assert old_reference is not None
    ipay_server.expire_link(old_reference)
    stored.payment_expires_at = datetime.now(UTC) - timedelta(minutes=1)

    response = await ipay_client.get(f"/api/v1/orders/{body['public_id']}/status")

    assert response.status_code == 200
    new_reference = stored.provider_reference
    assert new_reference is not None
    assert new_reference != old_reference
    assert response.json()["payment_url"] == "https://pay.test/checkout"
    assert len(ipay_server.created) == 2


async def test_get_status_handles_three_link_shapes(
    ipay_provider: IPayMoneyProvider,
    ipay_server: FakeIPayServer,
) -> None:
    order = Order(id=uuid4(), amount=1000)
    initiation = await ipay_provider.create_payment(order)
    reference = initiation.provider_reference

    initiated = await ipay_provider.get_status(reference)
    assert initiated.status is ProviderPaymentStatus.INITIATED

    ipay_server.succeed_link(reference, amount=1000)
    succeeded = await ipay_provider.get_status(reference)
    assert succeeded.status is ProviderPaymentStatus.SUCCEEDED
    assert succeeded.amount == 1000

    ipay_server.expire_link(reference)
    expired = await ipay_provider.get_status(reference)
    assert expired.status is ProviderPaymentStatus.CANCELLED
    assert expired.expired is True


async def test_webhook_with_invalid_secret_is_rejected(
    ipay_client: AsyncClient,
    ipay_server: FakeIPayServer,
    ebook_repository: InMemoryEbookRepository,
    order_repository: InMemoryOrderRepository,
) -> None:
    await seed_ebook(ebook_repository)
    body = await create_ipay_order(ipay_client)
    stored = order_repository.orders[UUID(body["public_id"])]
    assert stored.provider_reference is not None
    ipay_server.succeed_link(stored.provider_reference, amount=stored.amount)

    response = await send_ipay_webhook(
        ipay_client,
        order_reference=stored.provider_reference,
        transaction_reference="ipay_tx_1",
        status_value="succeeded",
        amount=stored.amount,
        secret="mauvais-secret",
    )

    assert response.status_code == 403
    assert stored.status is OrderStatus.PENDING


async def test_webhook_valid_pays_order(
    ipay_client: AsyncClient,
    ipay_server: FakeIPayServer,
    ebook_repository: InMemoryEbookRepository,
    order_repository: InMemoryOrderRepository,
    fake_task_queue: FakeTaskQueue,
) -> None:
    await seed_ebook(ebook_repository)
    body = await create_ipay_order(ipay_client)
    stored = order_repository.orders[UUID(body["public_id"])]
    assert stored.provider_reference is not None
    ipay_server.succeed_link(stored.provider_reference, amount=stored.amount)
    ipay_server.set_transaction(
        "ipay_tx_1",
        status="succeeded",
        amount=stored.amount,
    )

    response = await send_ipay_webhook(
        ipay_client,
        order_reference=stored.provider_reference,
        transaction_reference="ipay_tx_1",
        status_value="succeeded",
        amount=stored.amount,
    )

    assert response.status_code == 204
    assert stored.status is OrderStatus.PAID
    assert fake_task_queue.fulfilled == [stored.id]
    status_response = await ipay_client.get(f"/api/v1/orders/{body['public_id']}/status")
    assert status_response.json()["payment_url"] is None


async def test_webhook_replayed_is_idempotent(
    ipay_client: AsyncClient,
    ipay_server: FakeIPayServer,
    ebook_repository: InMemoryEbookRepository,
    order_repository: InMemoryOrderRepository,
    fake_task_queue: FakeTaskQueue,
) -> None:
    await seed_ebook(ebook_repository)
    body = await create_ipay_order(ipay_client)
    stored = order_repository.orders[UUID(body["public_id"])]
    assert stored.provider_reference is not None
    ipay_server.succeed_link(stored.provider_reference, amount=stored.amount)
    ipay_server.set_transaction("ipay_tx_1", status="succeeded", amount=stored.amount)

    await send_ipay_webhook(
        ipay_client,
        order_reference=stored.provider_reference,
        transaction_reference="ipay_tx_1",
        status_value="succeeded",
        amount=stored.amount,
    )
    paid_at = stored.paid_at
    await send_ipay_webhook(
        ipay_client,
        order_reference=stored.provider_reference,
        transaction_reference="ipay_tx_1",
        status_value="succeeded",
        amount=stored.amount,
    )

    assert stored.status is OrderStatus.PAID
    assert stored.paid_at == paid_at
    assert len(fake_task_queue.fulfilled) == 1


async def test_webhook_out_of_order_does_not_revert_refund(
    ipay_client: AsyncClient,
    ipay_server: FakeIPayServer,
    ebook_repository: InMemoryEbookRepository,
    order_repository: InMemoryOrderRepository,
) -> None:
    await seed_ebook(ebook_repository)
    body = await create_ipay_order(ipay_client)
    stored = order_repository.orders[UUID(body["public_id"])]
    assert stored.provider_reference is not None
    ipay_server.set_transaction("ipay_tx_1", status="refunded", amount=stored.amount)

    await send_ipay_webhook(
        ipay_client,
        order_reference=stored.provider_reference,
        transaction_reference="ipay_tx_1",
        status_value="refunded",
        amount=stored.amount,
    )
    assert stored.status is OrderStatus.REFUNDED

    ipay_server.succeed_link(stored.provider_reference, amount=stored.amount)
    ipay_server.set_transaction("ipay_tx_1", status="succeeded", amount=stored.amount)
    await send_ipay_webhook(
        ipay_client,
        order_reference=stored.provider_reference,
        transaction_reference="ipay_tx_1",
        status_value="succeeded",
        amount=stored.amount,
    )

    assert stored.status is OrderStatus.REFUNDED


async def test_webhook_lower_amount_triggers_manual_review(
    ipay_client: AsyncClient,
    ipay_server: FakeIPayServer,
    ebook_repository: InMemoryEbookRepository,
    order_repository: InMemoryOrderRepository,
    repository: InMemoryAdminRepository,
    fake_task_queue: FakeTaskQueue,
) -> None:
    await seed_ebook(ebook_repository)
    body = await create_ipay_order(ipay_client)
    stored = order_repository.orders[UUID(body["public_id"])]
    assert stored.provider_reference is not None
    ipay_server.succeed_link(stored.provider_reference, amount=stored.amount)
    ipay_server.set_transaction(
        "ipay_tx_1",
        status="succeeded",
        amount=stored.amount - 1,
    )

    await send_ipay_webhook(
        ipay_client,
        order_reference=stored.provider_reference,
        transaction_reference="ipay_tx_1",
        status_value="succeeded",
        amount=stored.amount,
    )

    assert stored.status is OrderStatus.MANUAL_REVIEW
    assert fake_task_queue.fulfilled == []
    assert repository.audit_logs[-1].action is AdminAuditAction.PAYMENT_MANUAL_REVIEW


async def test_webhook_failed_is_not_terminal(
    ipay_client: AsyncClient,
    ipay_server: FakeIPayServer,
    ebook_repository: InMemoryEbookRepository,
    order_repository: InMemoryOrderRepository,
    fake_task_queue: FakeTaskQueue,
) -> None:
    await seed_ebook(ebook_repository)
    body = await create_ipay_order(ipay_client)
    stored = order_repository.orders[UUID(body["public_id"])]
    assert stored.provider_reference is not None
    ipay_server.fail_link(stored.provider_reference)

    await send_ipay_webhook(
        ipay_client,
        order_reference=stored.provider_reference,
        transaction_reference="ipay_tx_1",
        status_value="failed",
        amount=stored.amount,
        failure_reason="Insufficient funds",
    )

    assert stored.status.value == "pending"
    assert stored.payment_failure_reason == "Insufficient funds"

    ipay_server.succeed_link(stored.provider_reference, amount=stored.amount)
    ipay_server.set_transaction("ipay_tx_1", status="succeeded", amount=stored.amount)
    await send_ipay_webhook(
        ipay_client,
        order_reference=stored.provider_reference,
        transaction_reference="ipay_tx_1",
        status_value="succeeded",
        amount=stored.amount,
    )

    assert stored.status.value == "paid"
    assert fake_task_queue.fulfilled == [stored.id]


async def test_webhook_refund_revokes_download_tokens(
    ipay_client: AsyncClient,
    ipay_server: FakeIPayServer,
    ebook_repository: InMemoryEbookRepository,
    order_repository: InMemoryOrderRepository,
) -> None:
    await seed_ebook(ebook_repository)
    body = await create_ipay_order(ipay_client)
    stored = order_repository.orders[UUID(body["public_id"])]
    assert stored.provider_reference is not None
    ipay_server.succeed_link(stored.provider_reference, amount=stored.amount)
    ipay_server.set_transaction("ipay_tx_1", status="succeeded", amount=stored.amount)
    await send_ipay_webhook(
        ipay_client,
        order_reference=stored.provider_reference,
        transaction_reference="ipay_tx_1",
        status_value="succeeded",
        amount=stored.amount,
    )

    ipay_server.set_transaction("ipay_tx_1", status="refunded", amount=stored.amount)
    await send_ipay_webhook(
        ipay_client,
        order_reference=stored.provider_reference,
        transaction_reference="ipay_tx_1",
        status_value="refunded",
        amount=stored.amount,
    )

    assert stored.status is OrderStatus.REFUNDED
    assert stored.id in order_repository.revoked_order_ids


async def test_lost_webhook_is_recovered_by_reconciliation(
    ipay_client: AsyncClient,
    ipay_server: FakeIPayServer,
    ebook_repository: InMemoryEbookRepository,
    order_repository: InMemoryOrderRepository,
    ipay_service: OrderService,
    fake_task_queue: FakeTaskQueue,
) -> None:
    await seed_ebook(ebook_repository)
    body = await create_ipay_order(ipay_client)
    stored = order_repository.orders[UUID(body["public_id"])]
    assert stored.provider_reference is not None
    ipay_server.succeed_link(stored.provider_reference, amount=stored.amount)
    stored.created_at = datetime.now(UTC) - timedelta(minutes=6)

    changed = await ipay_service.reconcile_payment_orders()

    assert changed == 1
    assert stored.status is OrderStatus.PAID
    assert fake_task_queue.fulfilled == [stored.id]


async def test_reference_never_leaks_in_logs_or_public_response(
    ipay_client: AsyncClient,
    ipay_server: FakeIPayServer,
    ebook_repository: InMemoryEbookRepository,
    order_repository: InMemoryOrderRepository,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await seed_ebook(ebook_repository)
    caplog.set_level(logging.INFO)
    body = await create_ipay_order(ipay_client)
    stored = order_repository.orders[UUID(body["public_id"])]
    assert stored.provider_reference is not None
    reference = stored.provider_reference
    ipay_server.succeed_link(reference, amount=stored.amount)
    ipay_server.set_transaction("ipay_tx_1", status="succeeded", amount=stored.amount)
    await send_ipay_webhook(
        ipay_client,
        order_reference=reference,
        transaction_reference="ipay_tx_1",
        status_value="succeeded",
        amount=stored.amount,
    )

    status_response = await ipay_client.get(f"/api/v1/orders/{body['public_id']}/status")

    assert reference not in caplog.text
    assert reference not in status_response.text
    assert "provider_reference" not in status_response.json()


@pytest.mark.skipif(
    os.environ.get("IPAY_SANDBOX_TESTS") != "1",
    reason="Tests sandbox iPay Money désactivés.",
)
async def test_sandbox_link_roundtrip() -> None:
    secret_key = os.environ.get("IPAY_SECRET_KEY")
    if not secret_key:
        pytest.skip("IPAY_SECRET_KEY absent.")
    provider = IPayMoneyProvider(
        secret_key,
        os.environ.get("IPAY_WEBHOOK_SECRET"),
        FRONTEND_BASE_URL,
        "sandbox",
        "https://i-pay.money/api/v1",
    )
    order = Order(id=uuid4(), amount=50)
    initiation = await provider.create_payment(order)
    status = await provider.get_status(initiation.provider_reference)
    assert status.status is ProviderPaymentStatus.INITIATED
