from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from app.core.deps import RequireAdminDep, VideoServiceDep
from app.core.errors import ForbiddenError
from app.schemas.video import ExternalVideoCreate, VideoRead, VideoUploadTicket

admin_ebooks_router = APIRouter(prefix="/admin/ebooks")
admin_videos_router = APIRouter(prefix="/admin/videos")
webhooks_router = APIRouter(prefix="/webhooks")


@admin_ebooks_router.post(
    "/{ebook_id}/video/upload-url",
    response_model=VideoUploadTicket,
    status_code=status.HTTP_201_CREATED,
)
async def create_video_upload(
    ebook_id: UUID,
    _: RequireAdminDep,
    service: VideoServiceDep,
) -> VideoUploadTicket:
    return await service.create_upload(ebook_id)


@admin_ebooks_router.post(
    "/{ebook_id}/video/external",
    response_model=VideoRead,
    status_code=status.HTTP_201_CREATED,
)
async def attach_external_video(
    ebook_id: UUID,
    payload: ExternalVideoCreate,
    _: RequireAdminDep,
    service: VideoServiceDep,
) -> VideoRead:
    return await service.attach_external(ebook_id, payload.url)


@admin_ebooks_router.delete("/{ebook_id}/video", status_code=status.HTTP_204_NO_CONTENT)
async def detach_video(
    ebook_id: UUID,
    _: RequireAdminDep,
    service: VideoServiceDep,
) -> None:
    await service.detach(ebook_id)


@admin_videos_router.post("/{video_id}/refresh", response_model=VideoRead)
async def refresh_video(
    video_id: UUID,
    _: RequireAdminDep,
    service: VideoServiceDep,
) -> VideoRead:
    return await service.refresh(video_id)


@webhooks_router.post("/cloudflare-stream", status_code=status.HTTP_204_NO_CONTENT)
async def cloudflare_stream_webhook(
    request: Request,
    service: VideoServiceDep,
) -> Response:
    body = await request.body()
    signature = request.headers.get("Webhook-Signature")
    if not service.verify_webhook_signature(signature, body):
        raise ForbiddenError("Signature de webhook invalide.")
    await service.handle_webhook(body)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
