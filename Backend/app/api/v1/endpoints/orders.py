from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response, status

from app.core.deps import OrderServiceDep, RequireAdminDep
from app.core.request import client_ip
from app.models.enums import OrderStatus
from app.repositories.order import OrderAdminFilters
from app.schemas.order import (
    AdminOrderListResponse,
    AdminOrderRead,
    OrderCreate,
    OrderCreateResponse,
    OrderStatusResponse,
)

public_router = APIRouter(prefix="/orders")
webhooks_router = APIRouter(prefix="/webhooks/payments")
admin_router = APIRouter(prefix="/admin/orders")


@public_router.post(
    "",
    response_model=OrderCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_order(
    payload: OrderCreate,
    request: Request,
    service: OrderServiceDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> OrderCreateResponse:
    return await service.create_order(payload, idempotency_key, client_ip(request))


@public_router.get("/{public_id}/status", response_model=OrderStatusResponse)
async def get_order_status(
    public_id: UUID,
    service: OrderServiceDep,
) -> OrderStatusResponse:
    return await service.get_public_status(public_id)


@webhooks_router.post("/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def payment_webhook(
    provider: str,
    request: Request,
    service: OrderServiceDep,
) -> Response:
    await service.handle_webhook(provider, request)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.get("", response_model=AdminOrderListResponse)
async def list_admin_orders(
    _: RequireAdminDep,
    service: OrderServiceDep,
    status_filter: Annotated[
        str | None,
        Query(alias="status", pattern="^(pending|paid|failed|refunded)$"),
    ] = None,
    ebook_id: UUID | None = None,
    ebook_slug: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    payment_method: str | None = None,
    email: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminOrderListResponse:
    filters = OrderAdminFilters(
        status=OrderStatus(status_filter) if status_filter is not None else None,
        ebook_id=ebook_id,
        ebook_slug=ebook_slug,
        date_from=date_from,
        date_to=date_to,
        payment_method=payment_method,
        email=email,
    )
    return await service.list_admin_orders(filters, page, page_size)


@admin_router.get("/{order_id}", response_model=AdminOrderRead)
async def get_admin_order(
    order_id: UUID,
    _: RequireAdminDep,
    service: OrderServiceDep,
) -> AdminOrderRead:
    return await service.get_admin_order(order_id)
