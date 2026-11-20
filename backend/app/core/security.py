from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from jwt.exceptions import InvalidTokenError as JwtInvalidTokenError

from app.core.config import get_settings

ALGORITHM = "HS256"
DEFAULT_ACCESS_TOKEN_TTL = timedelta(minutes=15)


def create_access_token(
    subject: str,
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(UTC)
    expires_at = now + (expires_delta or DEFAULT_ACCESS_TOKEN_TTL)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, get_settings().SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, get_settings().SECRET_KEY, algorithms=[ALGORITHM])
    except JwtInvalidTokenError as exc:
        raise ValueError("Jeton invalide") from exc
