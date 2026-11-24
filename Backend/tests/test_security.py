from datetime import timedelta

import pytest
from app.core.security import create_access_token, decode_token


def test_access_token_roundtrip() -> None:
    token = create_access_token(
        "user-1",
        expires_delta=timedelta(minutes=5),
        extra_claims={"role": "admin"},
    )

    payload = decode_token(token)

    assert payload["sub"] == "user-1"
    assert payload["role"] == "admin"


def test_invalid_token_is_rejected() -> None:
    with pytest.raises(ValueError, match="Jeton invalide"):
        decode_token("not-a-valid-token")
