import hmac
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, ClassVar

from fastapi import Request

from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError, ServiceUnavailableError
from app.models.enums import OrderStatus
from app.models.order import Order

WEBHOOK_SECRET_HEADER = "Secret-Hash"


@dataclass(frozen=True, slots=True)
class PaymentInitiation:
    provider_reference: str
    redirect_url: str | None = None
    instructions: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    status: OrderStatus


class PaymentProvider(ABC):
    code: ClassVar[str]

    @abstractmethod
    async def create_payment(self, order: Order) -> PaymentInitiation: ...

    @abstractmethod
    async def get_status(self, provider_reference: str) -> ProviderStatus: ...

    @abstractmethod
    async def verify_webhook(self, request: Request) -> bool: ...

    @abstractmethod
    def extract_reference(self, payload: Mapping[str, Any]) -> str | None: ...


class FakePaymentProvider(PaymentProvider):
    code: ClassVar[str] = "fake"

    def __init__(
        self,
        webhook_secret: str,
        redirect_base_url: str = "https://fake-payments.test/checkout",
    ) -> None:
        self._webhook_secret = webhook_secret
        self._redirect_base_url = redirect_base_url.rstrip("/")
        self._statuses: dict[str, OrderStatus] = {}
        self._default_status = OrderStatus.PENDING

    async def create_payment(self, order: Order) -> PaymentInitiation:
        reference = f"fake_{order.id}"
        self._statuses.setdefault(reference, self._default_status)
        return PaymentInitiation(
            provider_reference=reference,
            redirect_url=f"{self._redirect_base_url}/{reference}",
            instructions="Paiement simulé. Validez la transaction de test pour continuer.",
        )

    async def get_status(self, provider_reference: str) -> ProviderStatus:
        return ProviderStatus(status=self._statuses.get(provider_reference, self._default_status))

    async def verify_webhook(self, request: Request) -> bool:
        provided = request.headers.get(WEBHOOK_SECRET_HEADER)
        if not provided or not self._webhook_secret:
            return False
        return hmac.compare_digest(provided, self._webhook_secret)

    def extract_reference(self, payload: Mapping[str, Any]) -> str | None:
        reference = payload.get("reference")
        return reference if isinstance(reference, str) and reference else None

    def set_status(self, provider_reference: str, status: OrderStatus) -> None:
        self._statuses[provider_reference] = status

    def set_default_status(self, status: OrderStatus) -> None:
        self._default_status = status


class IPayMoneyProvider(PaymentProvider):
    code: ClassVar[str] = "ipay_money"

    def __init__(
        self,
        public_key: str | None,
        private_key: str | None,
        base_url: str,
        environment: str,
        webhook_secret: str | None,
    ) -> None:
        self._public_key = public_key
        self._private_key = private_key
        self._base_url = base_url.rstrip("/")
        self._environment = environment
        self._webhook_secret = webhook_secret

    async def create_payment(self, order: Order) -> PaymentInitiation:
        raise ServiceUnavailableError("La création de paiement iPay Money n'est pas documentée.")

    async def get_status(self, provider_reference: str) -> ProviderStatus:
        raise ServiceUnavailableError(
            "La consultation de transaction iPay Money n'est pas documentée."
        )

    async def verify_webhook(self, request: Request) -> bool:
        provided = request.headers.get(WEBHOOK_SECRET_HEADER)
        if not provided or not self._webhook_secret:
            return False
        return hmac.compare_digest(provided, self._webhook_secret)

    def extract_reference(self, payload: Mapping[str, Any]) -> str | None:
        data = payload.get("data")
        if not isinstance(data, Mapping):
            return None
        reference = data.get("reference")
        return reference if isinstance(reference, str) and reference else None


class PaymentProviderRegistry:
    def __init__(self, providers: Mapping[str, PaymentProvider]) -> None:
        self._providers = dict(providers)

    def get(self, code: str) -> PaymentProvider | None:
        return self._providers.get(code)

    def require(self, code: str) -> PaymentProvider:
        provider = self.get(code)
        if provider is None:
            raise NotFoundError("Fournisseur de paiement inconnu.")
        return provider

    def for_method(self, method: str, mapping: Mapping[str, str]) -> PaymentProvider | None:
        code = mapping.get(method)
        if code is None:
            return None
        return self.get(code)

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))


def build_payment_registry(settings: Settings) -> PaymentProviderRegistry:
    providers: dict[str, PaymentProvider] = {
        "ipay_money": IPayMoneyProvider(
            settings.IPAY_MONEY_PUBLIC_KEY,
            settings.IPAY_MONEY_PRIVATE_KEY,
            settings.IPAY_MONEY_BASE_URL,
            settings.IPAY_MONEY_ENV,
            settings.IPAY_MONEY_WEBHOOK_SECRET,
        )
    }
    if settings.fake_payments_enabled:
        providers["fake"] = FakePaymentProvider(settings.PAYMENT_FAKE_WEBHOOK_SECRET)
    return PaymentProviderRegistry(providers)


@lru_cache
def get_payment_registry() -> PaymentProviderRegistry:
    return build_payment_registry(get_settings())
