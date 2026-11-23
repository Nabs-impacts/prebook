from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from math import ceil
from uuid import UUID

from app.core.config import get_settings
from app.core.errors import BadRequestError, ConflictError, NotFoundError, TooManyRequestsError
from app.core.slug import slugify
from app.models.ebook import Ebook
from app.models.review import Review
from app.repositories.catalog_cache import CatalogCacheRepository
from app.repositories.ebook import EbookRepository
from app.repositories.order import OrderRepository
from app.repositories.review import REVIEW_FILTERS, ReviewRepository
from app.repositories.review_rate_limit import ReviewRateLimitRepository
from app.schemas.ebook import (
    AdminEbookListResponse,
    AdminEbookRead,
    AdminReviewListResponse,
    AdminReviewRead,
    EbookCreate,
    EbookDetail,
    EbookListItem,
    EbookListResponse,
    EbookUpdate,
    ReviewCreate,
    ReviewListResponse,
    ReviewRead,
)
from app.schemas.settings import SiteSettings
from app.services.settings import SettingsService
from app.services.storage import StorageBackend

PDF_MAGIC = b"%PDF-"
PDF_EXTENSION = ".pdf"
COVER_EXTENSIONS = {
    b"\x89PNG\r\n\x1a\n": ".png",
    b"\xff\xd8\xff": ".jpg",
}
SUMMARY_FALLBACK_LENGTH = 200


def _count_reader(value: int) -> Callable[[], Awaitable[int]]:
    async def read() -> int:
        return value

    return read


def derive_summary(description: str) -> str:
    compact = " ".join(description.split())
    if len(compact) <= SUMMARY_FALLBACK_LENGTH:
        return compact
    return f"{compact[:SUMMARY_FALLBACK_LENGTH].rstrip()}..."


def detect_cover_extension(content: bytes) -> str | None:
    for signature, extension in COVER_EXTENSIONS.items():
        if content.startswith(signature):
            return extension
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    return None


class EbookService:
    def __init__(
        self,
        ebook_repository: EbookRepository,
        review_repository: ReviewRepository,
        order_repository: OrderRepository,
        cache_repository: CatalogCacheRepository,
        rate_limit_repository: ReviewRateLimitRepository,
        settings_service: SettingsService,
        storage_backend: StorageBackend,
    ) -> None:
        self._ebook_repository = ebook_repository
        self._review_repository = review_repository
        self._order_repository = order_repository
        self._cache_repository = cache_repository
        self._rate_limit_repository = rate_limit_repository
        self._settings_service = settings_service
        self._storage_backend = storage_backend

    async def list_public_ebooks(self, page: int, page_size: int) -> EbookListResponse:
        settings = await self._settings_service.get_settings()
        version = await self._cache_repository.get_version()
        key = self._cache_repository.list_key(
            version,
            page,
            page_size,
            settings.show_reviews_count,
            settings.show_purchases_count,
        )
        cached = await self._cache_repository.get_response(key)
        if cached is not None:
            return EbookListResponse.model_validate_json(cached)

        offset = (page - 1) * page_size
        rows = await self._ebook_repository.list_published(offset, page_size)
        total = await self._ebook_repository.count_published()
        ids = [row.id for row in rows]
        reviews_counts, purchases_counts = await self._bulk_counts(ids, settings)

        items: list[EbookListItem] = []
        for row in rows:
            counts = await self._settings_service.resolve_optional_counts(
                _count_reader(reviews_counts.get(row.id, 0)),
                _count_reader(purchases_counts.get(row.id, 0)),
                settings=settings,
            )
            items.append(
                EbookListItem(
                    id=row.id,
                    title=row.title,
                    slug=row.slug,
                    price=row.price,
                    cover_url=row.cover_url,
                    summary=row.summary,
                    reviews_count=counts.reviews_count,
                    purchases_count=counts.purchases_count,
                )
            )

        response = EbookListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=ceil(total / page_size) if total else 0,
        )
        await self._cache_repository.set_response(key, response.model_dump_json())
        return response

    async def get_public_detail(self, slug: str) -> EbookDetail:
        settings = await self._settings_service.get_settings()
        version = await self._cache_repository.get_version()
        key = self._cache_repository.detail_key(
            version,
            slug,
            settings.show_reviews_count,
            settings.show_purchases_count,
        )
        cached = await self._cache_repository.get_response(key)
        if cached is not None:
            return EbookDetail.model_validate_json(cached)

        result = await self._ebook_repository.get_detail_by_slug(slug)
        if result is None:
            raise NotFoundError("Ebook introuvable.")
        ebook, average_rating = result
        counts = await self._settings_service.resolve_optional_counts(
            lambda: self._review_count(ebook.id),
            lambda: self._purchase_count(ebook.id),
            settings=settings,
        )
        detail = EbookDetail(
            id=ebook.id,
            title=ebook.title,
            slug=ebook.slug,
            description=ebook.description,
            summary=ebook.summary,
            price=ebook.price,
            cover_url=ebook.cover_url,
            preview_video_id=ebook.preview_video_id,
            average_rating=round(average_rating, 2) if average_rating is not None else None,
            reviews_count=counts.reviews_count,
            purchases_count=counts.purchases_count,
        )
        await self._cache_repository.set_response(key, detail.model_dump_json())
        return detail

    async def list_public_reviews(
        self,
        slug: str,
        page: int,
        page_size: int,
    ) -> ReviewListResponse:
        version = await self._cache_repository.get_version()
        key = self._cache_repository.reviews_key(version, slug, page, page_size)
        cached = await self._cache_repository.get_response(key)
        if cached is not None:
            return ReviewListResponse.model_validate_json(cached)

        ebook = await self._ebook_repository.get_by_slug(slug, published_only=True)
        if ebook is None:
            raise NotFoundError("Ebook introuvable.")

        offset = (page - 1) * page_size
        reviews = await self._review_repository.list_approved(ebook.id, offset, page_size)
        total = await self._review_repository.count_approved(ebook.id)
        response = ReviewListResponse(
            items=[self._review_read(review) for review in reviews],
            total=total,
            page=page,
            page_size=page_size,
            pages=ceil(total / page_size) if total else 0,
        )
        await self._cache_repository.set_response(key, response.model_dump_json())
        return response

    async def create_review(self, slug: str, data: ReviewCreate, ip: str) -> ReviewRead:
        config = get_settings()
        attempts = await self._rate_limit_repository.hit(
            ip,
            config.REVIEW_RATE_LIMIT_WINDOW_SECONDS,
        )
        if attempts > config.REVIEW_RATE_LIMIT_ATTEMPTS:
            raise TooManyRequestsError()

        ebook = await self._ebook_repository.get_by_slug(slug, published_only=True)
        if ebook is None:
            raise NotFoundError("Ebook introuvable.")

        review = Review(
            ebook_id=ebook.id,
            author_name=data.author_name,
            rating=data.rating,
            comment=data.comment,
            is_approved=False,
        )
        created = await self._review_repository.create(review)
        await self._review_repository.commit()
        return self._review_read(created)

    async def list_admin_ebooks(self, page: int, page_size: int) -> AdminEbookListResponse:
        offset = (page - 1) * page_size
        ebooks = await self._ebook_repository.list_admin(offset, page_size)
        total = await self._ebook_repository.count_admin()
        return AdminEbookListResponse(
            items=[self._admin_ebook_read(ebook) for ebook in ebooks],
            total=total,
            page=page,
            page_size=page_size,
            pages=ceil(total / page_size) if total else 0,
        )

    async def create_ebook(self, data: EbookCreate) -> AdminEbookRead:
        slug = await self._unique_slug(data.title)
        summary = data.summary or derive_summary(data.description)
        ebook = Ebook(
            title=data.title,
            slug=slug,
            description=data.description,
            summary=summary,
            price=data.price,
            cover_url="",
            pdf_storage_key="",
            preview_video_id=data.preview_video_id,
            is_published=False,
        )
        created = await self._ebook_repository.create(ebook)
        await self._ebook_repository.commit()
        await self._cache_repository.bump_version()
        return self._admin_ebook_read(created)

    async def update_ebook(self, ebook_id: UUID, data: EbookUpdate) -> AdminEbookRead:
        ebook = await self._ebook_repository.get_by_id(ebook_id, for_update=True)
        if ebook is None:
            raise NotFoundError("Ebook introuvable.")

        if data.title is not None:
            ebook.title = data.title
        if data.description is not None:
            ebook.description = data.description
        if data.price is not None:
            ebook.price = data.price
        if "preview_video_id" in data.model_fields_set:
            ebook.preview_video_id = data.preview_video_id
        if data.summary is not None:
            ebook.summary = data.summary or derive_summary(ebook.description)
        if data.is_published is not None:
            if data.is_published:
                self._ensure_publishable(ebook)
            ebook.is_published = data.is_published

        await self._ebook_repository.commit()
        await self._cache_repository.bump_version()
        return self._admin_ebook_read(ebook)

    async def publish_ebook(self, ebook_id: UUID) -> AdminEbookRead:
        ebook = await self._ebook_repository.get_by_id(ebook_id, for_update=True)
        if ebook is None:
            raise NotFoundError("Ebook introuvable.")
        self._ensure_publishable(ebook)
        ebook.is_published = True
        await self._ebook_repository.commit()
        await self._cache_repository.bump_version()
        return self._admin_ebook_read(ebook)

    async def unpublish_ebook(self, ebook_id: UUID) -> AdminEbookRead:
        ebook = await self._ebook_repository.get_by_id(ebook_id, for_update=True)
        if ebook is None:
            raise NotFoundError("Ebook introuvable.")
        ebook.is_published = False
        await self._ebook_repository.commit()
        await self._cache_repository.bump_version()
        return self._admin_ebook_read(ebook)

    async def delete_ebook(self, ebook_id: UUID) -> None:
        ebook = await self._ebook_repository.get_by_id(ebook_id, for_update=True)
        if ebook is None:
            raise NotFoundError("Ebook introuvable.")

        if await self._order_repository.exists_for_ebook(ebook_id):
            ebook.is_published = False
            ebook.deleted_at = datetime.now(UTC)
        else:
            await self._ebook_repository.delete(ebook)
        await self._ebook_repository.commit()
        await self._cache_repository.invalidate_counters(ebook_id)
        await self._cache_repository.bump_version()

    async def upload_pdf(
        self,
        ebook_id: UUID,
        content: bytes,
        content_type: str | None,
    ) -> AdminEbookRead:
        config = get_settings()
        if len(content) > config.MAX_PDF_UPLOAD_BYTES:
            raise BadRequestError("Le PDF dépasse la taille maximale autorisée.")
        if not content:
            raise BadRequestError("Le fichier PDF est vide.")
        if content_type not in (None, "application/pdf") or not content.startswith(PDF_MAGIC):
            raise BadRequestError("Le fichier fourni n'est pas un PDF valide.")

        ebook = await self._ebook_repository.get_by_id(ebook_id, for_update=True)
        if ebook is None:
            raise NotFoundError("Ebook introuvable.")
        stored = await self._storage_backend.save_pdf(content, PDF_EXTENSION)
        previous_key = ebook.pdf_storage_key
        ebook.pdf_storage_key = stored.key
        await self._ebook_repository.commit()
        if previous_key:
            await self._storage_backend.delete(previous_key)
        await self._cache_repository.bump_version()
        return self._admin_ebook_read(ebook)

    async def upload_cover(
        self,
        ebook_id: UUID,
        content: bytes,
        content_type: str | None,
    ) -> AdminEbookRead:
        config = get_settings()
        if len(content) > config.MAX_COVER_UPLOAD_BYTES:
            raise BadRequestError("L'image dépasse la taille maximale autorisée.")
        if not content:
            raise BadRequestError("Le fichier image est vide.")
        extension = detect_cover_extension(content)
        if extension is None or content_type not in (None, "image/png", "image/jpeg", "image/webp"):
            raise BadRequestError("Le fichier fourni n'est pas une image valide.")

        ebook = await self._ebook_repository.get_by_id(ebook_id, for_update=True)
        if ebook is None:
            raise NotFoundError("Ebook introuvable.")
        stored = await self._storage_backend.save_cover(content, extension)
        if stored.url is None:
            raise BadRequestError("Impossible de stocker l'image.")
        ebook.cover_url = stored.url
        await self._ebook_repository.commit()
        await self._cache_repository.bump_version()
        return self._admin_ebook_read(ebook)

    async def list_admin_reviews(
        self,
        status: str,
        page: int,
        page_size: int,
    ) -> AdminReviewListResponse:
        if status not in REVIEW_FILTERS:
            raise BadRequestError("Statut de modération invalide.")
        offset = (page - 1) * page_size
        rows = await self._review_repository.list_admin(status, offset, page_size)
        total = await self._review_repository.count_admin(status)
        items = [
            AdminReviewRead(
                **self._review_read(row.review).model_dump(),
                ebook_id=row.review.ebook_id,
                ebook_title=row.ebook_title,
                is_approved=row.review.is_approved,
            )
            for row in rows
        ]
        return AdminReviewListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=ceil(total / page_size) if total else 0,
        )

    async def approve_review(self, review_id: UUID) -> ReviewRead:
        review = await self._review_repository.get_by_id(review_id)
        if review is None:
            raise NotFoundError("Avis introuvable.")
        was_approved = review.is_approved
        review.is_approved = True
        await self._review_repository.commit()
        if not was_approved:
            await self._cache_repository.invalidate_counters(review.ebook_id)
            await self._cache_repository.bump_version()
        return self._review_read(review)

    async def delete_review(self, review_id: UUID) -> None:
        review = await self._review_repository.get_by_id(review_id)
        if review is None:
            raise NotFoundError("Avis introuvable.")
        was_approved = review.is_approved
        ebook_id = review.ebook_id
        await self._review_repository.delete(review)
        await self._review_repository.commit()
        if was_approved:
            await self._cache_repository.invalidate_counters(ebook_id)
            await self._cache_repository.bump_version()

    async def invalidate_catalog(self) -> None:
        await self._cache_repository.bump_version()

    async def on_order_paid(self, ebook_id: UUID) -> None:
        await self._cache_repository.invalidate_counters(ebook_id)
        await self._cache_repository.bump_version()

    async def _bulk_counts(
        self,
        ebook_ids: list[UUID],
        settings: SiteSettings,
    ) -> tuple[dict[UUID, int], dict[UUID, int]]:
        reviews_counts: dict[UUID, int] = {}
        purchases_counts: dict[UUID, int] = {}
        if settings.show_reviews_count:
            reviews_counts = await self._cache_repository.get_many_counters(
                "reviews",
                ebook_ids,
            )
            missing = [ebook_id for ebook_id in ebook_ids if ebook_id not in reviews_counts]
            if missing:
                computed = await self._review_repository.count_approved_by_ebooks(missing)
                for ebook_id in missing:
                    computed.setdefault(ebook_id, 0)
                await self._cache_repository.set_many_counters("reviews", computed)
                reviews_counts.update(computed)
        if settings.show_purchases_count:
            purchases_counts = await self._cache_repository.get_many_counters(
                "purchases",
                ebook_ids,
            )
            missing = [ebook_id for ebook_id in ebook_ids if ebook_id not in purchases_counts]
            if missing:
                computed = await self._order_repository.count_paid_by_ebooks(missing)
                for ebook_id in missing:
                    computed.setdefault(ebook_id, 0)
                await self._cache_repository.set_many_counters("purchases", computed)
                purchases_counts.update(computed)
        return reviews_counts, purchases_counts

    async def _review_count(self, ebook_id: UUID) -> int:
        cached = await self._cache_repository.get_counter("reviews", ebook_id)
        if cached is not None:
            return cached
        count = await self._review_repository.count_approved(ebook_id)
        await self._cache_repository.set_counter("reviews", ebook_id, count)
        return count

    async def _purchase_count(self, ebook_id: UUID) -> int:
        cached = await self._cache_repository.get_counter("purchases", ebook_id)
        if cached is not None:
            return cached
        count = await self._order_repository.count_paid_by_ebook(ebook_id)
        await self._cache_repository.set_counter("purchases", ebook_id, count)
        return count

    async def _unique_slug(self, title: str) -> str:
        base = slugify(title)
        candidate = base
        suffix = 2
        while await self._ebook_repository.slug_exists(candidate):
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    def _ensure_publishable(self, ebook: Ebook) -> None:
        if not ebook.cover_url:
            raise ConflictError("Une image de couverture est requise avant publication.")
        if not ebook.pdf_storage_key:
            raise ConflictError("Un fichier PDF est requis avant publication.")

    def _review_read(self, review: Review) -> ReviewRead:
        return ReviewRead(
            id=review.id,
            author_name=review.author_name,
            rating=review.rating,
            comment=review.comment,
            created_at=review.created_at,
        )

    def _admin_ebook_read(self, ebook: Ebook) -> AdminEbookRead:
        return AdminEbookRead(
            id=ebook.id,
            title=ebook.title,
            slug=ebook.slug,
            description=ebook.description,
            summary=ebook.summary,
            price=ebook.price,
            cover_url=ebook.cover_url,
            has_pdf=bool(ebook.pdf_storage_key),
            preview_video_id=ebook.preview_video_id,
            is_published=ebook.is_published,
            deleted_at=ebook.deleted_at,
            created_at=ebook.created_at,
        )
