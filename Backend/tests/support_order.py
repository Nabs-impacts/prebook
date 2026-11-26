from uuid import UUID

from app.models.ebook import Ebook

from tests.support_catalog import InMemoryEbookRepository


class FakeTaskQueue:
    def __init__(self) -> None:
        self.fulfilled: list[UUID] = []

    async def enqueue_fulfill_order(self, order_id: UUID) -> None:
        self.fulfilled.append(order_id)


async def seed_ebook(
    repository: InMemoryEbookRepository,
    slug: str = "guide-prebook",
    price: int = 7500,
    title: str = "Guide Prebook",
    is_published: bool = True,
) -> Ebook:
    ebook = Ebook(
        title=title,
        slug=slug,
        description="Une description de test.",
        summary="Un résumé.",
        price=price,
        cover_url="https://cdn.test/cover.png",
        pdf_storage_key="private/source.pdf",
        is_published=is_published,
    )
    return await repository.create(ebook)


def order_payload(
    slug: str = "guide-prebook",
    email: str = "buyer@example.com",
    name: str = "Acheteur Test",
) -> dict[str, str]:
    return {
        "ebook_slug": slug,
        "buyer_name": name,
        "buyer_email": email,
    }
