import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy.exc import IntegrityError

from app.core.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    TooManyRequestsError,
)
from app.core.text import mask_email
from app.models.enums import OrderStatus
from app.models.order import Order
from app.repositories.catalog_cache import CatalogCacheRepository
from app.repositories.ebook import EbookRepository
from app.repositories.order import (
    OrderAdminFilters,
    OrderAdminRow,
    OrderRepository,
)
from app.repositories.order_rate_limit import OrderRateLimitRepository
from app.schemas.order import (
    AdminOrderListResponse,
    AdminOrderRead,
    OrderCreate,
    OrderCreateResponse,
    OrderStatusResponse,
)
from app.schemas.settings import SiteSettings
from app.services.payment_provider import (
    PaymentInitiation,
    PaymentProvider,
    PaymentProviderRegistry,
    ProviderStatus,
)
from app.services.settings import SettingsService
from app.tasks.queue import TaskQueue

logger = logging.getLogger("prebook.orders")

PAYMENT_METHOD_SETTING_KEYS: dict[str, str] = {
    "mynita": "payment_mynita_enabled",
    "amanata": "payment_amanata_enabled",
    "airtel_money": "payment_airtel_money_enabled",
}

ALLOWED_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.PENDING: frozenset({OrderStatus.PAID, OrderStatus.FAILED}),
    OrderStatus.PAID: frozenset({OrderStatus.REFUNDED}),
    OrderStatus.FAILED: frozenset(),
    OrderStatus.REFUNDED: frozenset(),
}


class OrderService:
    def __init__(
        self,
        order_repository: OrderRepository,
        ebook_repository: EbookRepository,
        settings_service: SettingsService,
        payment_registry: PaymentProviderRegistry,
        rate_limit_repository: OrderRateLimitRepository,
        cache_repository: CatalogCacheRepository,
        task_queue: TaskQueue,
        *,
        payment_methods: Mapping[str, str],
        fake_payments_enabled: bool,
        rate_limit_attempts: int,
        rate_limit_window_seconds: int,
        pending_expiration_minutes: int,
        reconciliation_minutes: int,
        task_batch_size: int,
    ) -> None:
        self._order_repository = order_repository
        self._ebook_repository = ebook_repository
        self._settings_service = settings_service
        self._payment_registry = payment_registry
        self._rate_limit_repository = rate_limit_repository
        self._cache_repository = cache_repository
        self._task_queue = task_queue
        self._payment_methods = dict(payment_methods)
        self._fake_payments_enabled = fake_payments_enabled
        self._rate_limit_attempts = rate_limit_attempts
        self._rate_limit_window_seconds = rate_limit_window_seconds
        self._pending_expiration_minutes = pending_expiration_minutes
        self._reconciliation_minutes = reconciliation_minutes
        self._task_batch_size = task_batch_size

    async def create_order(
        self,
        data: OrderCreate,
        idempotency_key: str | None,
        ip: str,
    ) -> OrderCreateResponse:
        key = self._normalize_idempotency_key(idempotency_key)
        if key is not None:
            existing = await self._order_repository.get_by_idempotency_key(key)
            if existing is not None:
                return self._create_response(existing)

        attempts = await self._rate_limit_repository.hit(
            ip,
            self._rate_limit_window_seconds,
        )
        if attempts > self._rate_limit_attempts:
            raise TooManyRequestsError()

        settings = await self._settings_service.get_settings()
        provider = self._resolve_provider(data.payment_method, settings)
        ebook = await self._ebook_repository.get_by_slug(
            data.ebook_slug,
            published_only=True,
        )
        if ebook is None:
            raise NotFoundError("Ebook introuvable.")

        order = Order(
            buyer_email=str(data.buyer_email),
            buyer_name=data.buyer_name,
            ebook_id=ebook.id,
            amount=ebook.price,
            currency="XOF",
            status=OrderStatus.PENDING,
            provider=provider.code,
            payment_method=data.payment_method,
            idempotency_key=key,
        )
        try:
            created = await self._order_repository.create(order)
            await self._order_repository.commit()
        except IntegrityError:
            await self._order_repository.rollback()
            if key is not None:
                existing = await self._order_repository.get_by_idempotency_key(key)
                if existing is not None:
                    return self._create_response(existing)
            raise

        logger.info(
            "order_created",
            extra={
                "extra_fields": {
                    "order_id": str(created.id),
                    "provider": provider.code,
                    "amount": created.amount,
                    "email": mask_email(created.buyer_email),
                }
            },
        )

        try:
            initiation = await provider.create_payment(created)
        except Exception:
            created.status = OrderStatus.FAILED
            await self._order_repository.commit()
            logger.warning(
                "order_payment_initiation_failed",
                extra={
                    "extra_fields": {
                        "order_id": str(created.id),
                        "provider": provider.code,
                    }
                },
            )
            raise

        self._apply_initiation(created, initiation)
        await self._order_repository.commit()
        return self._create_response(created)

    async def get_public_status(self, public_id: UUID) -> OrderStatusResponse:
        order = await self._order_repository.get_by_id(public_id)
        if order is None:
            raise NotFoundError("Commande introuvable.")
        return OrderStatusResponse(
            public_id=order.id,
            status=order.status,
            amount=order.amount,
            currency=order.currency,
            payment_method=order.payment_method,
            created_at=order.created_at,
            paid_at=order.paid_at,
        )

    async def handle_webhook(self, provider_code: str, request: Request) -> None:
        provider = self._payment_registry.require(provider_code)
        if not await provider.verify_webhook(request):
            raise ForbiddenError("Signature de webhook invalide.")

        payload = await self._parse_webhook_body(request)
        reference = provider.extract_reference(payload)
        if reference is None:
            raise BadRequestError("Référence de paiement absente.")

        status = await provider.get_status(reference)
        order = await self._order_repository.get_by_provider_reference(
            provider.code,
            reference,
            for_update=True,
        )
        if order is None:
            return
        await self._apply_status(order, status.status)

    async def list_admin_orders(
        self,
        filters: OrderAdminFilters,
        page: int,
        page_size: int,
    ) -> AdminOrderListResponse:
        offset = (page - 1) * page_size
        rows = await self._order_repository.list_admin(filters, offset, page_size)
        total = await self._order_repository.count_admin(filters)
        return AdminOrderListResponse(
            items=[self._admin_read(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
            pages=ceil(total / page_size) if total else 0,
        )

    async def get_admin_order(self, order_id: UUID) -> AdminOrderRead:
        row = await self._order_repository.get_admin_detail(order_id)
        if row is None:
            raise NotFoundError("Commande introuvable.")
        return self._admin_read(row)

    async def expire_pending_orders(self) -> int:
        cutoff = datetime.now(UTC) - timedelta(minutes=self._pending_expiration_minutes)
        orders = await self._order_repository.list_pending_before(
            cutoff,
            self._task_batch_size,
        )
        changed = 0
        for order in orders:
            status = await self._provider_status(order)
            if status is None:
                continue
            target = OrderStatus.PAID if status.status is OrderStatus.PAID else OrderStatus.FAILED
            if await self._apply_status(order, target):
                changed += 1
        return changed

    async def reconcile_pending_orders(self) -> int:
        cutoff = datetime.now(UTC) - timedelta(minutes=self._reconciliation_minutes)
        orders = await self._order_repository.list_pending_before(
            cutoff,
            self._task_batch_size,
        )
        changed = 0
        for order in orders:
            status = await self._provider_status(order)
            if status is None:
                continue
            if status.status not in (OrderStatus.PAID, OrderStatus.FAILED):
                continue
            if await self._apply_status(order, status.status):
                changed += 1
        return changed

    async def _provider_status(self, order: Order) -> ProviderStatus | None:
        if not order.provider_reference:
            return None
        provider = self._payment_registry.get(order.provider)
        if provider is None:
            return None
        try:
            return await provider.get_status(order.provider_reference)
        except Exception:
            logger.warning(
                "order_status_check_failed",
                extra={
                    "extra_fields": {
                        "order_id": str(order.id),
                        "provider": order.provider,
                    }
                },
            )
            return None

    async def _apply_status(self, order: Order, target: OrderStatus) -> bool:
        if order.status is target:
            return False
        if target not in ALLOWED_TRANSITIONS[order.status]:
            raise ConflictError("Transition de statut de commande invalide.")

        order.status = target
        if target is OrderStatus.PAID:
            order.paid_at = datetime.now(UTC)
        await self._order_repository.commit()

        if target in (OrderStatus.PAID, OrderStatus.REFUNDED):
            await self._cache_repository.invalidate_counters(order.ebook_id)
            await self._cache_repository.bump_version()

        if target is OrderStatus.PAID:
            await self._task_queue.enqueue_fulfill_order(order.id)
            logger.info(
                "order_paid",
                extra={
                    "extra_fields": {
                        "order_id": str(order.id),
                        "provider": order.provider,
                        "amount": order.amount,
                        "email": mask_email(order.buyer_email),
                    }
                },
            )
        elif target is OrderStatus.FAILED:
            logger.info(
                "order_failed",
                extra={"extra_fields": {"order_id": str(order.id)}},
            )
        elif target is OrderStatus.REFUNDED:
            logger.info(
                "order_refunded",
                extra={"extra_fields": {"order_id": str(order.id)}},
            )
        return True

    def _resolve_provider(
        self,
        payment_method: str,
        settings: SiteSettings,
    ) -> PaymentProvider:
        provider = self._payment_registry.for_method(
            payment_method,
            self._payment_methods,
        )
        if provider is None:
            raise BadRequestError("Moyen de paiement invalide.")
        setting_key = PAYMENT_METHOD_SETTING_KEYS.get(payment_method)
        if setting_key is not None and not bool(getattr(settings, setting_key)):
            raise BadRequestError("Moyen de paiement désactivé.")
        if provider.code == "fake" and not self._fake_payments_enabled:
            raise BadRequestError("Moyen de paiement désactivé.")
        return provider

    def _normalize_idempotency_key(self, idempotency_key: str | None) -> str | None:
        if idempotency_key is None:
            return None
        key = idempotency_key.strip()
        if not key:
            raise BadRequestError("Clé d'idempotence invalide.")
        if len(key) > 255:
            raise BadRequestError("Clé d'idempotence invalide.")
        return key

    async def _parse_webhook_body(self, request: Request) -> dict[str, Any]:
        body = await request.body()
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError) as error:
            raise BadRequestError("Payload de webhook invalide.") from error
        if not isinstance(payload, dict):
            raise BadRequestError("Payload de webhook invalide.")
        return payload

    def _apply_initiation(self, order: Order, initiation: PaymentInitiation) -> None:
        order.provider_reference = initiation.provider_reference
        order.payment_url = initiation.redirect_url
        order.payment_instructions = initiation.instructions

    def _create_response(self, order: Order) -> OrderCreateResponse:
        return OrderCreateResponse(
            public_id=order.id,
            status=order.status,
            amount=order.amount,
            currency=order.currency,
            payment_method=order.payment_method,
            provider=order.provider,
            redirect_url=order.payment_url,
            instructions=order.payment_instructions,
            created_at=order.created_at,
        )

    def _admin_read(self, row: OrderAdminRow) -> AdminOrderRead:
        order = row.order
        return AdminOrderRead(
            id=order.id,
            buyer_name=order.buyer_name,
            buyer_email=order.buyer_email,
            ebook_id=order.ebook_id,
            ebook_title=row.ebook_title,
            ebook_slug=row.ebook_slug,
            amount=order.amount,
            currency=order.currency,
            status=order.status,
            provider=order.provider,
            provider_reference=order.provider_reference,
            payment_method=order.payment_method,
            payment_url=order.payment_url,
            payment_instructions=order.payment_instructions,
            paid_at=order.paid_at,
            created_at=order.created_at,
        )
