from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Query, Request, Response, UploadFile, status

from app.core.config import get_settings
from app.core.deps import EbookServiceDep, RequireAdminDep
from app.core.http import conditional_json_response
from app.core.request import client_ip
from app.schemas.ebook import (
    AdminEbookListResponse,
    AdminEbookRead,
    AdminReviewListResponse,
    EbookCreate,
    EbookDetail,
    EbookListResponse,
    EbookUpdate,
    ReviewCreate,
    ReviewListResponse,
    ReviewRead,
)

PUBLIC_CACHE_CONTROL = "public, max-age=60"

public_router = APIRouter(prefix="/ebooks")
admin_router = APIRouter(prefix="/admin/ebooks")
admin_reviews_router = APIRouter(prefix="/admin/reviews")


@public_router.get("", response_model=EbookListResponse)
async def list_ebooks(
    request: Request,
    service: EbookServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Response:
    result = await service.list_public_ebooks(page, page_size)
    return conditional_json_response(request, result.model_dump_json(), PUBLIC_CACHE_CONTROL)


@public_router.get("/{slug}", response_model=EbookDetail)
async def get_ebook(
    slug: str,
    request: Request,
    service: EbookServiceDep,
) -> Response:
    result = await service.get_public_detail(slug)
    return conditional_json_response(request, result.model_dump_json(), PUBLIC_CACHE_CONTROL)


@public_router.get("/{slug}/reviews", response_model=ReviewListResponse)
async def list_ebook_reviews(
    slug: str,
    request: Request,
    service: EbookServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Response:
    result = await service.list_public_reviews(slug, page, page_size)
    return conditional_json_response(request, result.model_dump_json(), PUBLIC_CACHE_CONTROL)


@public_router.post(
    "/{slug}/reviews",
    response_model=ReviewRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_ebook_review(
    slug: str,
    payload: ReviewCreate,
    request: Request,
    service: EbookServiceDep,
) -> ReviewRead:
    return await service.create_review(slug, payload, client_ip(request))


@admin_router.get("", response_model=AdminEbookListResponse)
async def list_admin_ebooks(
    _: RequireAdminDep,
    service: EbookServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminEbookListResponse:
    return await service.list_admin_ebooks(page, page_size)


@admin_router.post(
    "",
    response_model=AdminEbookRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_admin_ebook(
    payload: EbookCreate,
    _: RequireAdminDep,
    service: EbookServiceDep,
) -> AdminEbookRead:
    return await service.create_ebook(payload)


@admin_router.patch("/{ebook_id}", response_model=AdminEbookRead)
async def update_admin_ebook(
    ebook_id: UUID,
    payload: EbookUpdate,
    _: RequireAdminDep,
    service: EbookServiceDep,
) -> AdminEbookRead:
    return await service.update_ebook(ebook_id, payload)


@admin_router.post("/{ebook_id}/publish", response_model=AdminEbookRead)
async def publish_admin_ebook(
    ebook_id: UUID,
    _: RequireAdminDep,
    service: EbookServiceDep,
) -> AdminEbookRead:
    return await service.publish_ebook(ebook_id)


@admin_router.post("/{ebook_id}/unpublish", response_model=AdminEbookRead)
async def unpublish_admin_ebook(
    ebook_id: UUID,
    _: RequireAdminDep,
    service: EbookServiceDep,
) -> AdminEbookRead:
    return await service.unpublish_ebook(ebook_id)


@admin_router.delete("/{ebook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_admin_ebook(
    ebook_id: UUID,
    _: RequireAdminDep,
    service: EbookServiceDep,
) -> None:
    await service.delete_ebook(ebook_id)


@admin_router.post("/{ebook_id}/pdf", response_model=AdminEbookRead)
async def upload_admin_ebook_pdf(
    ebook_id: UUID,
    _: RequireAdminDep,
    service: EbookServiceDep,
    file: Annotated[UploadFile, File(...)],
) -> AdminEbookRead:
    content = await file.read(get_settings().MAX_PDF_UPLOAD_BYTES + 1)
    return await service.upload_pdf(ebook_id, content, file.content_type)


@admin_router.post("/{ebook_id}/cover", response_model=AdminEbookRead)
async def upload_admin_ebook_cover(
    ebook_id: UUID,
    _: RequireAdminDep,
    service: EbookServiceDep,
    file: Annotated[UploadFile, File(...)],
) -> AdminEbookRead:
    content = await file.read(get_settings().MAX_COVER_UPLOAD_BYTES + 1)
    return await service.upload_cover(ebook_id, content, file.content_type)


@admin_reviews_router.get("", response_model=AdminReviewListResponse)
async def list_admin_reviews(
    _: RequireAdminDep,
    service: EbookServiceDep,
    status_filter: Annotated[
        str, Query(alias="status", pattern="^(pending|approved|all)$")
    ] = "pending",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminReviewListResponse:
    return await service.list_admin_reviews(status_filter, page, page_size)


@admin_reviews_router.post("/{review_id}/approve", response_model=ReviewRead)
async def approve_admin_review(
    review_id: UUID,
    _: RequireAdminDep,
    service: EbookServiceDep,
) -> ReviewRead:
    return await service.approve_review(review_id)


@admin_reviews_router.delete("/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_admin_review(
    review_id: UUID,
    _: RequireAdminDep,
    service: EbookServiceDep,
) -> None:
    await service.delete_review(review_id)
