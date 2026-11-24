from fastapi import APIRouter

from app.api.v1.endpoints import admins, auth, ebooks, health, orders, settings, videos

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(admins.router, tags=["admins"])
api_router.include_router(settings.public_router, tags=["settings"])
api_router.include_router(settings.admin_router, tags=["settings"])
api_router.include_router(ebooks.public_router, tags=["ebooks"])
api_router.include_router(ebooks.admin_router, tags=["ebooks"])
api_router.include_router(ebooks.admin_reviews_router, tags=["reviews"])
api_router.include_router(videos.admin_ebooks_router, tags=["videos"])
api_router.include_router(videos.admin_videos_router, tags=["videos"])
api_router.include_router(videos.webhooks_router, tags=["webhooks"])
api_router.include_router(orders.public_router, tags=["orders"])
api_router.include_router(orders.admin_router, tags=["orders"])
api_router.include_router(orders.webhooks_router, tags=["webhooks"])
