import json
import logging
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Any
from uuid import UUID

from fastapi import BackgroundTasks, Request
from sqlalchemy.exc import IntegrityError

from app.core.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    TooManyRequestsError,
)
from app.core.text import mask_email
from app.models.enums import AdminAuditAction, OrderStatus
from app.models.order import Order
from app.repositories.admin import AdminRepository
from app.repositories.catalog_cache import CatalogCacheRepository
from app.repositories.ebook import EbookRepository
from app.repositories.order import (
    OrderAdminFilters,
    OrderAdminRow,
    OrderRepository,
)
from app.repositories.order_rate_limit import OrderRateLimitRepository
from app.repositories.payment_state import PaymentStateRepository
from app.schemas.order import (
    AdminOrderListResponse,
    AdminOrderRead,
    OrderCreate,
    OrderCreateResponse,
    OrderStatusResponse,
)
from app.services.payment_provider import (
    PaymentInitiation,
    PaymentProvider,
    PaymentProviderRegistry,
    ProviderPaymentStatus,
    ProviderStatus,
    WebhookEvent,
)
from app.services.settings import SettingsService
from app.tasks.queue import TaskQueue

logger = logging.getLogger("prebook.orders")

ALLOWED_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.PENDING: frozenset(
        {
            OrderStatus.PAID,
            OrderStatus.FAILED,
            OrderStatus.EXPIRED,
            OrderStatus.MANUAL_REVIEW,
            OrderStatus.REFUNDED,
        }
    ),
    OrderStatus.EXPIRED: frozenset(
        {
            OrderStatus.PAID,
            OrderStatus.FAILED,
            OrderStatus.MANUAL_REVIEW,
            OrderStatus.REFUNDED,
        }
    ),
    OrderStatus.MANUAL_REVIEW: frozenset(
        {
            OrderStatus.PAID,
            OrderStatus.FAILED,
            OrderStatus.REFUNDED,
        }
    ),
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
        admin_repository: AdminRepository,
        payment_state_repository: PaymentStateRepository,
        *,
        provider_code: str,
        rate_limit_attempts: int,
        rate_limit_window_seconds: int,
        reconciliation_max_age_minutes: int,
        reconciliation_interval_minutes: int,
        reconciliation_max_interval_minutes: int,
        task_batch_size: int,
    ) -> None:
        self._order_repository = order_repository
        self._ebook_repository = ebook_repository
        self._settings_service = settings_service
        self._payment_registry = payment_registry
        self._rate_limit_repository = rate_limit_repository
        self._cache_repository = cache_repository
        self._task_queue = task_queue
        self._admin_repository = admin_repository
        self._payment_state_repository = payment_state_repository
        self._provider_code = provider_code
        self._rate_limit_attempts = rate_limit_attempts
        self._rate_limit_window_seconds = rate_limit_window_seconds
        self._reconciliation_max_age_minutes = reconciliation_max_age_minutes
        self._reconciliation_interval_minutes = reconciliation_interval_minutes
        self._reconciliation_max_interval_minutes = reconciliation_max_interval_minutes
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
        if not settings.payments_enabled:
            raise BadRequestError("Les paiements sont temporairement désactivés.")
        provider = self._payment_registry.require(self._provider_code)
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
            created.payment_failure_reason = "payment_creation_failed"
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
        if (
            order.status is OrderStatus.PENDING
            and order.payment_expires_at is not None
            and order.payment_expires_at <= datetime.now(UTC)
        ):
            await self._refresh_expired_link(order)
        return self._status_response(order)

    async def handle_webhook(
        self,
        provider_code: str,
        request: Request,
        background_tasks: BackgroundTasks,
    ) -> None:
        provider = self._payment_registry.require(provider_code)
        if not await provider.verify_webhook(request):
            raise ForbiddenError("Signature de webhook invalide.")
        payload = await self._parse_webhook_body(request)
        event = provider.parse_webhook(payload)
        if event is None:
            raise BadRequestError("Payload de webhook invalide.")
        background_tasks.add_task(self.process_webhook_event, provider, event)

    async def process_webhook_event(
        self,
        provider: PaymentProvider,
        event: WebhookEvent,
    ) -> None:
        if event.status is None:
            return
        reference = event.transaction_reference or event.order_reference
        claimed = await self._payment_state_repository.claim_webhook_event(
            reference,
            event.status.value,
        )
        if not claimed:
            return
        order = await self._order_repository.get_by_provider_reference(
            provider.code,
            event.order_reference,
            for_update=True,
        )
        if order is None:
            return
        if event.status is ProviderPaymentStatus.SUCCEEDED:
            await self._process_success(order, provider, event)
        elif event.status is ProviderPaymentStatus.FAILED:
            await self._process_failed(order, provider, event)
        elif event.status is ProviderPaymentStatus.REFUNDED:
            await self._process_refund(order, provider, event)

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

    async def admin_refund_order(
        self,
        actor_id: UUID,
        order_id: UUID,
        ip: str | None,
    ) -> AdminOrderRead:
        order = await self._order_repository.get_by_id(order_id, for_update=True)
        if order is None:
            raise NotFoundError("Commande introuvable.")
        if order.status is not OrderStatus.REFUNDED:
            if OrderStatus.REFUNDED not in ALLOWED_TRANSITIONS[order.status]:
                raise ConflictError("Remboursement impossible pour ce statut.")
            await self._apply_status(order, OrderStatus.REFUNDED)
        await self._admin_repository.add_audit_log(
            actor_id,
            AdminAuditAction.ORDER_REFUNDED,
            order.id,
            ip,
        )
        await self._order_repository.commit()
        row = await self._order_repository.get_admin_detail(order_id)
        if row is None:
            raise NotFoundError("Commande introuvable.")
        return self._admin_read(row)

    async def admin_recheck_order(
        self,
        actor_id: UUID,
        order_id: UUID,
        ip: str | None,
    ) -> AdminOrderRead:
        order = await self._order_repository.get_by_id(order_id, for_update=True)
        if order is None:
            raise NotFoundError("Commande introuvable.")
        await self._reconcile_order(order, final=order.status is OrderStatus.EXPIRED)
        await self._admin_repository.add_audit_log(
            actor_id,
            AdminAuditAction.ORDER_RECHECKED,
            order.id,
            ip,
        )
        await self._order_repository.commit()
        row = await self._order_repository.get_admin_detail(order_id)
        if row is None:
            raise NotFoundError("Commande introuvable.")
        return self._admin_read(row)

    async def reconcile_payment_orders(self) -> int:
        now = datetime.now(UTC)
        cutoff = now - timedelta(minutes=self._reconciliation_max_age_minutes)
        pending = await self._order_repository.list_pending_created_after(
            cutoff,
            self._task_batch_size,
        )
        expired = await self._order_repository.list_expired_created_after(
            cutoff,
            self._task_batch_size,
        )
        changed = 0
        for order in pending:
            due = await self._payment_state_repository.reconciliation_due(
                order.id,
                now,
                self._reconciliation_interval_minutes,
                self._reconciliation_max_interval_minutes,
            )
            if not due:
                continue
            await self._payment_state_repository.record_reconciliation(order.id, now)
            if await self._reconcile_order(order, final=False):
                changed += 1
        for order in expired:
            if await self._reconcile_order(order, final=True):
                changed += 1
        return changed

    async def _refresh_expired_link(self, order: Order) -> None:
        provider = self._payment_registry.get(order.provider)
        if provider is None:
            return
        if order.provider_reference:
            try:
                status = await provider.get_status(order.provider_reference)
            except NotFoundError:
                status = None
            except Exception:
                logger.warning(
                    "payment_link_expiration_check_failed",
                    extra={"extra_fields": {"order_id": str(order.id)}},
                )
                status = None
            if status is not None:
                if status.status is ProviderPaymentStatus.SUCCEEDED:
                    await self._handle_verified_success(order, status)
                    return
                if status.status is ProviderPaymentStatus.REFUNDED:
                    await self._apply_status(order, OrderStatus.REFUNDED)
                    return
                if not status.expired and status.status is not ProviderPaymentStatus.CANCELLED:
                    return
        try:
            initiation = await provider.create_payment(order)
        except Exception:
            order.status = OrderStatus.FAILED
            order.payment_failure_reason = "payment_link_recreation_failed"
            await self._order_repository.commit()
            logger.warning(
                "order_payment_link_recreation_failed",
                extra={"extra_fields": {"order_id": str(order.id)}},
            )
            return
        self._apply_initiation(order, initiation)
        await self._order_repository.commit()
        logger.info(
            "order_payment_link_recreated",
            extra={"extra_fields": {"order_id": str(order.id)}},
        )

    async def _process_success(
        self,
        order: Order,
        provider: PaymentProvider,
        event: WebhookEvent,
    ) -> None:
        if order.status in (OrderStatus.PAID, OrderStatus.REFUNDED):
            return
        verified = await self._verify_success(order, provider, event)
        if verified is None:
            return
        await self._handle_verified_success(order, verified)

    async def _verify_success(
        self,
        order: Order,
        provider: PaymentProvider,
        event: WebhookEvent,
    ) -> ProviderStatus | None:
        if not order.provider_reference:
            return None
        try:
            link = await provider.get_status(order.provider_reference)
        except Exception:
            logger.warning(
                "payment_link_verification_failed",
                extra={"extra_fields": {"order_id": str(order.id)}},
            )
            return None
        if link.status is not ProviderPaymentStatus.SUCCEEDED:
            return None
        transaction: ProviderStatus | None = None
        if event.transaction_reference:
            try:
                transaction = await provider.get_transaction(event.transaction_reference)
            except NotFoundError:
                logger.info(
                    "ipay_transaction_lookup_not_found",
                    extra={"extra_fields": {"order_id": str(order.id)}},
                )
            except Exception:
                logger.warning(
                    "ipay_transaction_lookup_failed",
                    extra={"extra_fields": {"order_id": str(order.id)}},
                )
        if transaction is not None:
            if transaction.status is not ProviderPaymentStatus.SUCCEEDED:
                return None
            amount = transaction.amount if transaction.amount is not None else link.amount
        else:
            amount = link.amount
        return ProviderStatus(
            status=ProviderPaymentStatus.SUCCEEDED,
            amount=amount,
            net_amount=transaction.net_amount if transaction is not None else None,
            payment_method=transaction.payment_method if transaction is not None else None,
        )

    async def _handle_verified_success(
        self,
        order: Order,
        verified: ProviderStatus,
    ) -> None:
        if OrderStatus.PAID not in ALLOWED_TRANSITIONS[order.status]:
            return
        amount = verified.amount
        if amount is None or amount < order.amount:
            await self._mark_manual_review(order, amount)
            return
        await self._apply_status(order, OrderStatus.PAID)

    async def _process_failed(
        self,
        order: Order,
        provider: PaymentProvider,
        event: WebhookEvent,
    ) -> None:
        if order.status in (OrderStatus.PAID, OrderStatus.REFUNDED):
            return
        status: ProviderStatus | None = None
        if order.provider_reference:
            try:
                status = await provider.get_status(order.provider_reference)
            except Exception:
                status = None
        if status is not None and status.status is ProviderPaymentStatus.SUCCEEDED:
            await self._handle_verified_success(order, status)
            return
        if status is not None and status.status is ProviderPaymentStatus.REFUNDED:
            if OrderStatus.REFUNDED in ALLOWED_TRANSITIONS[order.status]:
                await self._apply_status(order, OrderStatus.REFUNDED)
            return
        if order.status in (
            OrderStatus.PENDING,
            OrderStatus.EXPIRED,
            OrderStatus.MANUAL_REVIEW,
        ):
            order.payment_failure_reason = event.failure_reason or (
                status.failure_reason if status is not None else None
            )
            await self._order_repository.commit()
            logger.info(
                "payment_failed_attempt",
                extra={"extra_fields": {"order_id": str(order.id)}},
            )

    async def _process_refund(
        self,
        order: Order,
        provider: PaymentProvider,
        event: WebhookEvent,
    ) -> None:
        if order.status is OrderStatus.REFUNDED:
            return
        verified = False
        if event.transaction_reference:
            try:
                transaction = await provider.get_transaction(event.transaction_reference)
            except NotFoundError:
                verified = True
            except Exception:
                verified = True
            else:
                if transaction is None or transaction.status is ProviderPaymentStatus.REFUNDED:
                    verified = True
        else:
            verified = True
        if not verified:
            return
        if OrderStatus.REFUNDED not in ALLOWED_TRANSITIONS[order.status]:
            return
        await self._apply_status(order, OrderStatus.REFUNDED)

    async def _reconcile_order(self, order: Order, *, final: bool) -> bool:
        provider = self._payment_registry.get(order.provider)
        if provider is None:
            return False
        if not order.provider_reference:
            if final and OrderStatus.FAILED in ALLOWED_TRANSITIONS[order.status]:
                return await self._apply_status(order, OrderStatus.FAILED)
            return False
        try:
            status = await provider.get_status(order.provider_reference)
        except NotFoundError:
            if final:
                return await self._apply_status(order, OrderStatus.FAILED)
            return await self._apply_status(order, OrderStatus.EXPIRED)
        except Exception:
            logger.warning(
                "order_status_check_failed",
                extra={"extra_fields": {"order_id": str(order.id)}},
            )
            return False

        if status.status is ProviderPaymentStatus.SUCCEEDED:
            if OrderStatus.PAID not in ALLOWED_TRANSITIONS[order.status]:
                return False
            if status.amount is None or status.amount < order.amount:
                await self._mark_manual_review(order, status.amount)
                return True
            return await self._apply_status(order, OrderStatus.PAID)
        if status.status is ProviderPaymentStatus.REFUNDED:
            if OrderStatus.REFUNDED not in ALLOWED_TRANSITIONS[order.status]:
                return False
            return await self._apply_status(order, OrderStatus.REFUNDED)
        if final:
            if OrderStatus.FAILED not in ALLOWED_TRANSITIONS[order.status]:
                return False
            return await self._apply_status(order, OrderStatus.FAILED)
        if status.expired or status.status is ProviderPaymentStatus.CANCELLED:
            if OrderStatus.EXPIRED not in ALLOWED_TRANSITIONS[order.status]:
                return False
            return await self._apply_status(order, OrderStatus.EXPIRED)
        if status.status is ProviderPaymentStatus.FAILED:
            order.payment_failure_reason = status.failure_reason
            await self._order_repository.commit()
        return False

    async def _mark_manual_review(self, order: Order, paid_amount: int | None) -> None:
        if order.status is OrderStatus.MANUAL_REVIEW:
            return
        if OrderStatus.MANUAL_REVIEW not in ALLOWED_TRANSITIONS[order.status]:
            return
        order.payment_failure_reason = "amount_mismatch"
        await self._apply_status(order, OrderStatus.MANUAL_REVIEW)
        await self._admin_repository.add_audit_log(
            None,
            AdminAuditAction.PAYMENT_MANUAL_REVIEW,
            order.id,
            None,
            new_value={
                "paid_amount": paid_amount,
                "expected_amount": order.amount,
            },
        )
        await self._order_repository.commit()
        logger.warning(
            "payment_amount_mismatch_manual_review",
            extra={"extra_fields": {"order_id": str(order.id)}},
        )

    async def _apply_status(self, order: Order, target: OrderStatus) -> bool:
        if order.status is target:
            return False
        if target not in ALLOWED_TRANSITIONS[order.status]:
            raise ConflictError("Transition de statut de commande invalide.")

        order.status = target
        if target is OrderStatus.PAID:
            order.paid_at = datetime.now(UTC)
            order.payment_failure_reason = None
        await self._order_repository.commit()

        if target in (OrderStatus.PAID, OrderStatus.REFUNDED):
            await self._cache_repository.invalidate_counters(order.ebook_id)
            await self._cache_repository.bump_version()

        if target is OrderStatus.REFUNDED:
            await self._order_repository.revoke_download_tokens(order.id)
            await self._order_repository.commit()

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
        elif target is OrderStatus.EXPIRED:
            logger.info(
                "order_expired",
                extra={"extra_fields": {"order_id": str(order.id)}},
            )
        elif target is OrderStatus.MANUAL_REVIEW:
            logger.info(
                "order_manual_review",
                extra={"extra_fields": {"order_id": str(order.id)}},
            )
        elif target is OrderStatus.REFUNDED:
            logger.info(
                "order_refunded",
                extra={"extra_fields": {"order_id": str(order.id)}},
            )
        return True

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
        order.payment_expires_at = initiation.expires_at
        order.payment_failure_reason = None

    def _create_response(self, order: Order) -> OrderCreateResponse:
        return OrderCreateResponse(
            public_id=order.id,
            status=order.status,
            amount=order.amount,
            currency=order.currency,
            provider=order.provider,
            payment_url=order.payment_url,
            payment_expires_at=order.payment_expires_at,
            created_at=order.created_at,
        )

    def _status_response(self, order: Order) -> OrderStatusResponse:
        return OrderStatusResponse(
            public_id=order.id,
            status=order.status,
            amount=order.amount,
            currency=order.currency,
            payment_url=order.payment_url if order.status is OrderStatus.PENDING else None,
            payment_expires_at=order.payment_expires_at,
            created_at=order.created_at,
            paid_at=order.paid_at,
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
            payment_url=order.payment_url,
            payment_expires_at=order.payment_expires_at,
            payment_failure_reason=order.payment_failure_reason,
            paid_at=order.paid_at,
            created_at=order.created_at,
        )
