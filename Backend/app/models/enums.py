from enum import Enum as PythonEnum
from enum import StrEnum


class UserRole(StrEnum):
    CUSTOMER = "customer"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


class OrderStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"
    EXPIRED = "expired"
    MANUAL_REVIEW = "manual_review"


class VideoProviderType(StrEnum):
    CLOUDFLARE_STREAM = "cloudflare_stream"
    EXTERNAL_URL = "external_url"


class VideoStatus(StrEnum):
    UPLOADING = "uploading"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class AdminAuditAction(StrEnum):
    LOGIN = "login"
    LOGIN_FAILED = "login_failed"
    ADMIN_CREATED = "admin_created"
    ADMIN_UPDATED = "admin_updated"
    ADMIN_DELETED = "admin_deleted"
    SETTINGS_UPDATED = "settings_updated"
    PAYMENT_MANUAL_REVIEW = "payment_manual_review"
    ORDER_REFUNDED = "order_refunded"
    ORDER_RECHECKED = "order_rechecked"


def enum_values(enum_type: type[PythonEnum]) -> list[str]:
    return [str(member.value) for member in enum_type]
