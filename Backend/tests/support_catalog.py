from collections.abc import Callable
from datetime import UTC, datetime
from math import ceil
from uuid import UUID, uuid4

from app.models.ebook import Ebook
from app.models.enums import OrderStatus
from app.models.order import Order
from app.models.review import Review
from app.repositories.ebook import EbookListRow
from app.repositories.order import OrderAdminFilters, OrderAdminRow
from app.repositories.review import AdminReviewRow


class InMemoryEbookRepository:
    def __init__(self, review_repository: "InMemoryReviewRepository | None" = None) -> None:
        self.ebooks: dict[UUID, Ebook] = {}
        self.review_repository = review_repository
        self.list_published_calls = 0
        self.count_published_calls = 0

    async def get_by_id(self, ebook_id: UUID, for_update: bool = False) -> Ebook | None:
        ebook = self.ebooks.get(ebook_id)
        if ebook is None or ebook.deleted_at is not None:
            return None
        return ebook

    async def get_by_slug(self, slug: str, published_only: bool = False) -> Ebook | None:
        for ebook in self.ebooks.values():
            if ebook.slug != slug or ebook.deleted_at is not None:
                continue
            if published_only and not ebook.is_published:
                continue
            return ebook
        return None

    async def get_detail_by_slug(self, slug: str) -> tuple[Ebook, float | None] | None:
        ebook = await self.get_by_slug(slug, published_only=True)
        if ebook is None:
            return None
        average = None
        if self.review_repository is not None:
            average = await self.review_repository.average_approved(ebook.id)
        return ebook, average

    async def list_published(self, offset: int, limit: int) -> list[EbookListRow]:
        self.list_published_calls += 1
        ebooks = [
            ebook
            for ebook in self.ebooks.values()
            if ebook.is_published and ebook.deleted_at is None
        ]
        ebooks.sort(key=lambda ebook: (ebook.created_at, ebook.id), reverse=True)
        return [
            EbookListRow(
                id=ebook.id,
                title=ebook.title,
                slug=ebook.slug,
                price=ebook.price,
                cover_url=ebook.cover_url,
                summary=ebook.summary,
            )
            for ebook in ebooks[offset : offset + limit]
        ]

    async def count_published(self) -> int:
        self.count_published_calls += 1
        return sum(
            1 for ebook in self.ebooks.values() if ebook.is_published and ebook.deleted_at is None
        )

    async def list_admin(self, offset: int, limit: int) -> list[Ebook]:
        ebooks = [ebook for ebook in self.ebooks.values() if ebook.deleted_at is None]
        ebooks.sort(key=lambda ebook: (ebook.created_at, ebook.id), reverse=True)
        return ebooks[offset : offset + limit]

    async def count_admin(self) -> int:
        return sum(1 for ebook in self.ebooks.values() if ebook.deleted_at is None)

    async def slug_exists(self, slug: str) -> bool:
        return any(ebook.slug == slug for ebook in self.ebooks.values())

    async def create(self, ebook: Ebook) -> Ebook:
        ebook.id = uuid4()
        ebook.created_at = datetime.now(UTC)
        self.ebooks[ebook.id] = ebook
        return ebook

    async def delete(self, ebook: Ebook) -> None:
        self.ebooks.pop(ebook.id, None)

    async def commit(self) -> None:
        return None


class InMemoryReviewRepository:
    def __init__(
        self,
        ebook_lookup: Callable[[UUID], Ebook | None] | None = None,
    ) -> None:
        self.reviews: dict[UUID, Review] = {}
        self.ebook_lookup = ebook_lookup
        self.count_approved_calls = 0
        self.count_approved_by_ebooks_calls = 0

    async def list_approved(
        self,
        ebook_id: UUID,
        offset: int,
        limit: int,
    ) -> list[Review]:
        reviews = [
            review
            for review in self.reviews.values()
            if review.ebook_id == ebook_id and review.is_approved
        ]
        reviews.sort(key=lambda review: (review.created_at, review.id), reverse=True)
        return reviews[offset : offset + limit]

    async def count_approved(self, ebook_id: UUID) -> int:
        self.count_approved_calls += 1
        return sum(
            1
            for review in self.reviews.values()
            if review.ebook_id == ebook_id and review.is_approved
        )

    async def count_approved_by_ebooks(self, ebook_ids: list[UUID]) -> dict[UUID, int]:
        self.count_approved_by_ebooks_calls += 1
        counts: dict[UUID, int] = {}
        for review in self.reviews.values():
            if review.ebook_id in ebook_ids and review.is_approved:
                counts[review.ebook_id] = counts.get(review.ebook_id, 0) + 1
        return counts

    async def average_approved(self, ebook_id: UUID) -> float | None:
        ratings = [
            review.rating
            for review in self.reviews.values()
            if review.ebook_id == ebook_id and review.is_approved
        ]
        if not ratings:
            return None
        return sum(ratings) / len(ratings)

    async def list_admin(
        self,
        status: str,
        offset: int,
        limit: int,
    ) -> list[AdminReviewRow]:
        reviews = list(self.reviews.values())
        if status == "pending":
            reviews = [review for review in reviews if not review.is_approved]
        elif status == "approved":
            reviews = [review for review in reviews if review.is_approved]
        reviews.sort(key=lambda review: (review.created_at, review.id), reverse=True)
        rows: list[AdminReviewRow] = []
        for review in reviews[offset : offset + limit]:
            ebook = self.ebook_lookup(review.ebook_id) if self.ebook_lookup else None
            rows.append(
                AdminReviewRow(
                    review=review,
                    ebook_title=ebook.title if ebook is not None else "",
                )
            )
        return rows

    async def count_admin(self, status: str) -> int:
        if status == "pending":
            return sum(1 for review in self.reviews.values() if not review.is_approved)
        if status == "approved":
            return sum(1 for review in self.reviews.values() if review.is_approved)
        return len(self.reviews)

    async def get_by_id(self, review_id: UUID) -> Review | None:
        return self.reviews.get(review_id)

    async def create(self, review: Review) -> Review:
        review.id = uuid4()
        review.created_at = datetime.now(UTC)
        self.reviews[review.id] = review
        return review

    async def delete(self, review: Review) -> None:
        self.reviews.pop(review.id, None)

    async def commit(self) -> None:
        return None


class InMemoryOrderRepository:
    def __init__(
        self,
        ebook_lookup: Callable[[UUID], Ebook | None] | None = None,
    ) -> None:
        self.orders: dict[UUID, Order] = {}
        self.paid_counts: dict[UUID, int] = {}
        self.ebook_ids_with_orders: set[UUID] = set()
        self.count_paid_by_ebook_calls = 0
        self.count_paid_by_ebooks_calls = 0
        self.ebook_lookup = ebook_lookup
        self._idempotency: dict[str, Order] = {}
        self._provider_references: dict[tuple[str, str], Order] = {}
        self.revoked_order_ids: set[UUID] = set()

    async def count_paid_by_ebook(self, ebook_id: UUID) -> int:
        self.count_paid_by_ebook_calls += 1
        return self.paid_counts.get(ebook_id, 0)

    async def count_paid_by_ebooks(self, ebook_ids: list[UUID]) -> dict[UUID, int]:
        self.count_paid_by_ebooks_calls += 1
        return {
            ebook_id: self.paid_counts[ebook_id]
            for ebook_id in ebook_ids
            if ebook_id in self.paid_counts
        }

    async def exists_for_ebook(self, ebook_id: UUID) -> bool:
        return ebook_id in self.ebook_ids_with_orders

    async def get_by_id(self, order_id: UUID, for_update: bool = False) -> Order | None:
        return self.orders.get(order_id)

    async def get_by_idempotency_key(self, idempotency_key: str) -> Order | None:
        return self._idempotency.get(idempotency_key)

    async def get_by_provider_reference(
        self,
        provider: str,
        provider_reference: str,
        for_update: bool = False,
    ) -> Order | None:
        return self._provider_references.get((provider, provider_reference))

    async def list_pending_created_after(self, cutoff: datetime, limit: int) -> list[Order]:
        orders = [
            order
            for order in self.orders.values()
            if order.status is OrderStatus.PENDING and order.created_at >= cutoff
        ]
        orders.sort(key=lambda order: (order.created_at, order.id))
        return orders[:limit]

    async def list_expired_created_after(self, cutoff: datetime, limit: int) -> list[Order]:
        orders = [
            order
            for order in self.orders.values()
            if order.status is OrderStatus.EXPIRED and order.created_at >= cutoff
        ]
        orders.sort(key=lambda order: (order.created_at, order.id))
        return orders[:limit]

    async def revoke_download_tokens(self, order_id: UUID) -> None:
        self.revoked_order_ids.add(order_id)

    async def list_admin(
        self,
        filters: OrderAdminFilters,
        offset: int,
        limit: int,
    ) -> list[OrderAdminRow]:
        rows = [
            self._admin_row(order)
            for order in self.orders.values()
            if self._matches(order, filters)
        ]
        rows.sort(key=lambda row: (row.order.created_at, row.order.id), reverse=True)
        return rows[offset : offset + limit]

    async def count_admin(self, filters: OrderAdminFilters) -> int:
        return sum(1 for order in self.orders.values() if self._matches(order, filters))

    async def get_admin_detail(self, order_id: UUID) -> OrderAdminRow | None:
        order = self.orders.get(order_id)
        if order is None:
            return None
        return self._admin_row(order)

    async def create(self, order: Order) -> Order:
        order.id = uuid4()
        order.created_at = datetime.now(UTC)
        self.orders[order.id] = order
        self._reindex()
        return order

    async def commit(self) -> None:
        self._reindex()

    async def rollback(self) -> None:
        return None

    def _reindex(self) -> None:
        self._idempotency = {
            order.idempotency_key: order for order in self.orders.values() if order.idempotency_key
        }
        self._provider_references = {
            (order.provider, order.provider_reference): order
            for order in self.orders.values()
            if order.provider_reference
        }

    def _matches(self, order: Order, filters: OrderAdminFilters) -> bool:
        if filters.status is not None and order.status is not filters.status:
            return False
        if filters.ebook_id is not None and order.ebook_id != filters.ebook_id:
            return False
        if filters.date_from is not None and order.created_at < filters.date_from:
            return False
        if filters.date_to is not None and order.created_at > filters.date_to:
            return False
        if filters.email and filters.email.strip().lower() not in order.buyer_email.lower():
            return False
        if filters.ebook_slug is not None:
            ebook = self.ebook_lookup(order.ebook_id) if self.ebook_lookup else None
            if ebook is None or ebook.slug != filters.ebook_slug:
                return False
        return True

    def _admin_row(self, order: Order) -> OrderAdminRow:
        ebook = self.ebook_lookup(order.ebook_id) if self.ebook_lookup else None
        return OrderAdminRow(
            order=order,
            ebook_title=ebook.title if ebook is not None else "",
            ebook_slug=ebook.slug if ebook is not None else "",
        )


def pages_for(total: int, page_size: int) -> int:
    return ceil(total / page_size) if total else 0
