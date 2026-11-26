import hmac
import secrets
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import lru_cache
from typing import Any, ClassVar, Literal
from urllib.parse import quote

import httpx
from fastapi import Request

from app.core.config import Settings, get_settings
from app.core.errors import BadRequestError, NotFoundError, ServiceUnavailableError
from app.models.order import Order

WEBHOOK_SECRET_HEADER = "Secret-Hash"
IPAY_MIN_AMOUNT = 50


class ProviderPaymentStatus(StrEnum):
    INITIATED = "initiated"
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


def parse_provider_status(value: object) -> ProviderPaymentStatus | None:
    if not isinstance(value, str):
        return None
    try:
        return ProviderPaymentStatus(value)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class PaymentInitiation:
    provider_reference: str
    redirect_url: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    status: ProviderPaymentStatus
    amount: int | None = None
    net_amount: int | None = None
    failure_reason: str | None = None
    payment_method: str | None = None
    transaction_reference: str | None = None
    expired: bool = False


@dataclass(frozen=True, slots=True)
class WebhookEvent:
    order_reference: str
    transaction_reference: str | None
    status: ProviderPaymentStatus | None
    amount: int | None = None
    net_amount: int | None = None
    failure_reason: str | None = None
    payment_method: str | None = None


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


class PaymentProvider(ABC):
    code: ClassVar[str]

    @abstractmethod
    async def create_payment(self, order: Order) -> PaymentInitiation: ...

    @abstractmethod
    async def get_status(self, provider_reference: str) -> ProviderStatus: ...

    @abstractmethod
    async def verify_webhook(self, request: Request) -> bool: ...

    @abstractmethod
    def parse_webhook(self, payload: Mapping[str, Any]) -> WebhookEvent | None: ...

    async def get_transaction(self, reference: str) -> ProviderStatus | None:
        return None


class FakePaymentProvider(PaymentProvider):
    code: ClassVar[str] = "fake"

    def __init__(
        self,
        webhook_secret: str,
        redirect_base_url: str = "https://fake-payments.test/checkout",
        link_minutes: int = 30,
    ) -> None:
        self._webhook_secret = webhook_secret
        self._redirect_base_url = redirect_base_url.rstrip("/")
        self._link_minutes = link_minutes
        self._statuses: dict[str, ProviderPaymentStatus] = {}
        self._amounts: dict[str, int] = {}
        self._default_status = ProviderPaymentStatus.PENDING

    async def create_payment(self, order: Order) -> PaymentInitiation:
        reference = f"fake_{order.id}"
        self._statuses.setdefault(reference, self._default_status)
        self._amounts[reference] = order.amount
        return PaymentInitiation(
            provider_reference=reference,
            redirect_url=f"{self._redirect_base_url}/{reference}",
            expires_at=datetime.now(UTC) + timedelta(minutes=self._link_minutes),
        )

    async def get_status(self, provider_reference: str) -> ProviderStatus:
        status = self._statuses.get(provider_reference, self._default_status)
        return ProviderStatus(
            status=status,
            amount=self._amounts.get(provider_reference),
            transaction_reference=provider_reference,
        )

    async def get_transaction(self, reference: str) -> ProviderStatus | None:
        return await self.get_status(reference)

    async def verify_webhook(self, request: Request) -> bool:
        provided = request.headers.get(WEBHOOK_SECRET_HEADER)
        if not provided or not self._webhook_secret:
            return False
        return hmac.compare_digest(provided, self._webhook_secret)

    def parse_webhook(self, payload: Mapping[str, Any]) -> WebhookEvent | None:
        data = payload.get("data")
        source: Mapping[str, Any] = data if isinstance(data, Mapping) else payload
        order_reference = source.get("external_payment_reference") or source.get("reference")
        if not isinstance(order_reference, str) or not order_reference:
            return None
        transaction_reference = _str_or_none(source.get("reference"))
        return WebhookEvent(
            order_reference=order_reference,
            transaction_reference=transaction_reference,
            status=parse_provider_status(source.get("status")),
            amount=_int_or_none(source.get("amount")),
            net_amount=_int_or_none(source.get("net_amount")),
            failure_reason=_str_or_none(source.get("failure_reason")),
            payment_method=_str_or_none(source.get("payment_method")),
        )

    def set_status(self, provider_reference: str, status: ProviderPaymentStatus) -> None:
        self._statuses[provider_reference] = status

    def set_default_status(self, status: ProviderPaymentStatus) -> None:
        self._default_status = status


class IPayMoneyProvider(PaymentProvider):
    code: ClassVar[str] = "ipay_money"

    def __init__(
        self,
        secret_key: str | None,
        webhook_secret: str | None,
        frontend_base_url: str,
        environment: Literal["sandbox", "live"] = "sandbox",
        base_url: str = "https://i-pay.money/api/v1",
        *,
        link_minutes: int = 30,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._secret_key = secret_key
        self._webhook_secret = webhook_secret
        self._frontend_base_url = frontend_base_url.rstrip("/")
        self._environment = environment
        self._base_url = base_url.rstrip("/")
        self._link_minutes = link_minutes
        self._timeout = timeout
        self._transport = transport

    def _headers(self, payment_type: str, *, authenticated: bool = True) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Ipay-Target-Environment": self._environment,
            "Ipay-Payment-Type": payment_type,
        }
        if authenticated:
            if not self._secret_key:
                raise ServiceUnavailableError("Clé secrète iPay Money non configurée.")
            headers["Authorization"] = f"Bearer {self._secret_key}"
        return headers

    def _redirect_urls(self, order: Order) -> tuple[str, str]:
        if not self._frontend_base_url.startswith("https://"):
            raise ServiceUnavailableError("FRONTEND_BASE_URL doit être une URL HTTPS.")
        success_url = f"{self._frontend_base_url}/orders/{order.id}/success"
        failure_url = f"{self._frontend_base_url}/orders/{order.id}/failure"
        return success_url, failure_url

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport,
            timeout=self._timeout,
        )

    async def create_payment(self, order: Order) -> PaymentInitiation:
        if order.amount < IPAY_MIN_AMOUNT:
            raise BadRequestError("Le montant minimum iPay Money est de 50 XOF.")
        reference = secrets.token_urlsafe(32)
        success_url, failure_url = self._redirect_urls(order)
        payload = {
            "title": f"Commande {order.id}",
            "description": f"Transaction de la commande {order.id}",
            "amount": order.amount,
            "reference": reference,
            "shouldExpire": True,
            "on_success_redirection_url": success_url,
            "on_failed_redirection_url": failure_url,
        }
        async with self._client() as client:
            try:
                response = await client.post(
                    f"{self._base_url}/external_payments",
                    json=payload,
                    headers=self._headers("external_payment"),
                )
            except httpx.TimeoutException as error:
                raise ServiceUnavailableError(
                    "Délai dépassé lors de la création du lien de paiement."
                ) from error
            except httpx.HTTPError as error:
                raise ServiceUnavailableError(
                    "Erreur réseau lors de la création du lien de paiement."
                ) from error
        if response.status_code == 404:
            raise ServiceUnavailableError("Compte iPay Money introuvable pour cet environnement.")
        if response.status_code == 422:
            raise BadRequestError("Lien de paiement iPay Money refusé.")
        if response.status_code != 200:
            raise ServiceUnavailableError("Création du lien de paiement iPay Money impossible.")
        data = self._json(response)
        page_url = _str_or_none(data.get("page_url"))
        if page_url is None:
            raise ServiceUnavailableError("Réponse iPay Money invalide.")
        provider_reference = _str_or_none(data.get("reference")) or reference
        return PaymentInitiation(
            provider_reference=provider_reference,
            redirect_url=page_url,
            expires_at=datetime.now(UTC) + timedelta(minutes=self._link_minutes),
        )

    async def get_status(self, provider_reference: str) -> ProviderStatus:
        url = f"{self._base_url}/external_payments/{quote(provider_reference, safe='')}"
        async with self._client() as client:
            try:
                response = await client.get(url, headers={"Accept": "application/json"})
            except httpx.HTTPError as error:
                raise ServiceUnavailableError(
                    "Consultation du lien de paiement iPay Money impossible."
                ) from error
        if response.status_code == 404:
            raise NotFoundError("Lien de paiement introuvable.")
        if response.status_code != 200:
            raise ServiceUnavailableError("Consultation du lien de paiement iPay Money impossible.")
        data = self._json(response)
        raw_status = data.get("status")
        if data.get("has_expire") is True or raw_status == "cancelled":
            return ProviderStatus(
                status=ProviderPaymentStatus.CANCELLED,
                expired=True,
                transaction_reference=_str_or_none(data.get("transaction_id")),
            )
        status = parse_provider_status(raw_status)
        if status is None:
            raise ServiceUnavailableError("Statut de lien iPay Money inconnu.")
        return ProviderStatus(
            status=status,
            amount=_int_or_none(data.get("amount")),
            failure_reason=_str_or_none(data.get("failure_reason")),
            transaction_reference=_str_or_none(data.get("transaction_id")),
        )

    async def get_transaction(self, reference: str) -> ProviderStatus | None:
        url = f"{self._base_url}/payments/{quote(reference, safe='')}"
        async with self._client() as client:
            try:
                response = await client.get(url, headers=self._headers("mobile"))
            except httpx.HTTPError as error:
                raise ServiceUnavailableError(
                    "Consultation de la transaction iPay Money impossible."
                ) from error
        if response.status_code == 404:
            raise NotFoundError("Transaction iPay Money introuvable.")
        if response.status_code != 200:
            raise ServiceUnavailableError("Consultation de la transaction iPay Money impossible.")
        data = self._json(response)
        status = parse_provider_status(data.get("status"))
        if status is None:
            raise ServiceUnavailableError("Statut de transaction iPay Money inconnu.")
        return ProviderStatus(
            status=status,
            amount=_int_or_none(data.get("amount")),
            net_amount=_int_or_none(data.get("net_amount")),
            failure_reason=_str_or_none(data.get("failure_reason")),
            payment_method=_str_or_none(data.get("payment_method")),
            transaction_reference=_str_or_none(data.get("reference")),
        )

    async def verify_webhook(self, request: Request) -> bool:
        provided = request.headers.get(WEBHOOK_SECRET_HEADER)
        if not provided or not self._webhook_secret:
            return False
        return hmac.compare_digest(provided, self._webhook_secret)

    def parse_webhook(self, payload: Mapping[str, Any]) -> WebhookEvent | None:
        data = payload.get("data")
        if not isinstance(data, Mapping):
            return None
        order_reference = data.get("external_payment_reference")
        if not isinstance(order_reference, str) or not order_reference:
            return None
        return WebhookEvent(
            order_reference=order_reference,
            transaction_reference=_str_or_none(data.get("reference")),
            status=parse_provider_status(data.get("status")),
            amount=_int_or_none(data.get("amount")),
            net_amount=_int_or_none(data.get("net_amount")),
            failure_reason=_str_or_none(data.get("failure_reason")),
            payment_method=_str_or_none(data.get("payment_method")),
        )

    def _json(self, response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as error:
            raise ServiceUnavailableError("Réponse iPay Money invalide.") from error
        if not isinstance(payload, dict):
            raise ServiceUnavailableError("Réponse iPay Money invalide.")
        return payload


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

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))


def build_payment_registry(settings: Settings) -> PaymentProviderRegistry:
    providers: dict[str, PaymentProvider] = {
        "ipay_money": IPayMoneyProvider(
            settings.IPAY_SECRET_KEY,
            settings.IPAY_WEBHOOK_SECRET,
            settings.FRONTEND_BASE_URL,
            settings.IPAY_ENVIRONMENT,
            settings.IPAY_BASE_URL,
            link_minutes=settings.ORDER_PAYMENT_LINK_MINUTES,
        )
    }
    if settings.fake_payments_enabled:
        providers["fake"] = FakePaymentProvider(settings.PAYMENT_FAKE_WEBHOOK_SECRET)
    return PaymentProviderRegistry(providers)


@lru_cache
def get_payment_registry() -> PaymentProviderRegistry:
    return build_payment_registry(get_settings())
