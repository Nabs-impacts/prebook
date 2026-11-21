import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from jwt.exceptions import InvalidTokenError as JwtInvalidTokenError

from app.core.config import get_settings

ALGORITHM = "HS256"
DEFAULT_ACCESS_TOKEN_TTL = timedelta(minutes=15)
DEFAULT_REFRESH_TOKEN_TTL = timedelta(days=7)
ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"

password_hasher = PasswordHasher()


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _create_token(
    subject: str,
    token_type: str,
    expires_delta: timedelta,
    extra_claims: dict[str, Any] | None = None,
) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires_at = now + expires_delta
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "jti": uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)
    token = jwt.encode(payload, get_settings().SECRET_KEY, algorithm=ALGORITHM)
    return token, expires_at


def create_access_token(
    subject: str,
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    token, _ = _create_token(
        subject,
        ACCESS_TOKEN_TYPE,
        expires_delta or DEFAULT_ACCESS_TOKEN_TTL,
        extra_claims,
    )
    return token


def create_refresh_token(
    subject: str,
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    token, _ = _create_token(
        subject,
        REFRESH_TOKEN_TYPE,
        expires_delta or DEFAULT_REFRESH_TOKEN_TTL,
        extra_claims,
    )
    return token


def create_token_pair(subject: str, extra_claims: dict[str, Any] | None = None) -> TokenPair:
    settings = get_settings()
    access_token, access_expires_at = _create_token(
        subject,
        ACCESS_TOKEN_TYPE,
        timedelta(minutes=settings.ACCESS_TOKEN_TTL_MINUTES),
        extra_claims,
    )
    refresh_token, refresh_expires_at = _create_token(
        subject,
        REFRESH_TOKEN_TYPE,
        timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS),
        extra_claims,
    )
    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        access_expires_at=access_expires_at,
        refresh_expires_at=refresh_expires_at,
    )


def decode_token(token: str, expected_type: str | None = None) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            get_settings().SECRET_KEY,
            algorithms=[ALGORITHM],
            options={"require": ["exp", "sub", "type", "jti"]},
        )
    except JwtInvalidTokenError as exc:
        raise ValueError("Jeton invalide") from exc
    if expected_type is not None and payload.get("type") != expected_type:
        raise ValueError("Jeton invalide")
    return payload


def token_expiration(payload: dict[str, Any]) -> datetime:
    return datetime.fromtimestamp(int(payload["exp"]), UTC)
