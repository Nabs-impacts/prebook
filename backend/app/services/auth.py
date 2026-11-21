from uuid import UUID

from app.core.config import get_settings
from app.core.errors import ForbiddenError, TooManyRequestsError, UnauthorizedError
from app.core.security import (
    ACCESS_TOKEN_TYPE,
    REFRESH_TOKEN_TYPE,
    TokenPair,
    create_token_pair,
    decode_token,
    hash_password,
    token_expiration,
    verify_password,
)
from app.models.enums import AdminAuditAction, UserRole
from app.models.user import User
from app.repositories.admin import ADMIN_ROLES, AdminRepository
from app.repositories.login_attempt import LoginAttemptRepository
from app.repositories.token import TokenRepository
from app.schemas.auth import TokenResponse

LOGIN_ERROR_MESSAGE = "Email ou mot de passe incorrect."
DUMMY_PASSWORD_HASH = hash_password("prebook-dummy-password")


class AuthService:
    def __init__(
        self,
        admin_repository: AdminRepository,
        token_repository: TokenRepository,
        login_attempt_repository: LoginAttemptRepository,
    ) -> None:
        self._admin_repository = admin_repository
        self._token_repository = token_repository
        self._login_attempt_repository = login_attempt_repository

    def _token_response(self, pair: TokenPair) -> TokenResponse:
        return TokenResponse(
            access_token=pair.access_token,
            refresh_token=pair.refresh_token,
            expires_in=get_settings().ACCESS_TOKEN_TTL_MINUTES * 60,
        )

    async def login(self, email: str, password: str, ip: str) -> TokenResponse:
        settings = get_settings()
        attempts = await self._login_attempt_repository.increment(
            ip,
            email,
            settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        )
        if attempts > settings.LOGIN_RATE_LIMIT_ATTEMPTS:
            raise TooManyRequestsError()

        user = await self._admin_repository.get_by_email(email)
        password_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
        password_valid = verify_password(password, password_hash)
        if user is None or not user.is_active or user.role not in ADMIN_ROLES or not password_valid:
            raise UnauthorizedError(LOGIN_ERROR_MESSAGE)

        await self._login_attempt_repository.reset(ip, email)
        pair = create_token_pair(str(user.id), {"role": user.role.value})
        await self._token_repository.store_refresh(
            user.id,
            pair.refresh_token,
            pair.refresh_expires_at,
        )
        await self._admin_repository.add_audit_log(
            user.id,
            AdminAuditAction.LOGIN,
            user.id,
            ip,
        )
        await self._admin_repository.commit()
        return self._token_response(pair)

    async def refresh(self, refresh_token: str) -> TokenResponse:
        try:
            decode_token(refresh_token, REFRESH_TOKEN_TYPE)
        except ValueError as exc:
            raise UnauthorizedError("Jeton de rafraîchissement invalide.") from exc

        user_id = await self._token_repository.consume_refresh(refresh_token)
        if user_id is None:
            raise UnauthorizedError("Jeton de rafraîchissement invalide.")

        user = await self._admin_repository.get_by_id(user_id)
        if user is None or not user.is_active or user.role not in ADMIN_ROLES:
            await self._token_repository.revoke_all_for_user(user_id)
            raise UnauthorizedError("Jeton de rafraîchissement invalide.")

        pair = create_token_pair(str(user.id), {"role": user.role.value})
        await self._token_repository.store_refresh(
            user.id,
            pair.refresh_token,
            pair.refresh_expires_at,
        )
        return self._token_response(pair)

    async def logout(self, refresh_token: str | None, access_token: str | None) -> None:
        if refresh_token:
            await self._token_repository.revoke_refresh(refresh_token)
        if access_token:
            try:
                payload = decode_token(access_token, ACCESS_TOKEN_TYPE)
            except ValueError:
                return
            await self._token_repository.revoke_access(
                str(payload["jti"]),
                token_expiration(payload),
            )

    async def current_user(self, access_token: str) -> User:
        try:
            payload = decode_token(access_token, ACCESS_TOKEN_TYPE)
        except ValueError as exc:
            raise UnauthorizedError() from exc

        if await self._token_repository.is_access_revoked(str(payload["jti"])):
            raise UnauthorizedError()

        try:
            user_id = UUID(str(payload["sub"]))
        except ValueError as exc:
            raise UnauthorizedError() from exc

        user = await self._admin_repository.get_by_id(user_id)
        if user is None or not user.is_active:
            raise UnauthorizedError()
        return user


def ensure_admin(user: User) -> User:
    if user.role not in ADMIN_ROLES:
        raise ForbiddenError()
    return user


def ensure_super_admin(user: User) -> User:
    if user.role is not UserRole.SUPER_ADMIN:
        raise ForbiddenError()
    return user
