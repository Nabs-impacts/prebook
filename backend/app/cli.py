import argparse
import asyncio
import os

from pydantic import EmailStr, TypeAdapter, ValidationError

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import dispose_engine, get_session_factory
from app.models.enums import AdminAuditAction, UserRole
from app.models.user import User
from app.repositories.admin import AdminRepository


async def create_super_admin(email: str, password: str) -> None:
    settings = get_settings()
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        raise SystemExit(
            f"Le mot de passe doit contenir au moins {settings.PASSWORD_MIN_LENGTH} caractères."
        )

    normalized_email = str(TypeAdapter(EmailStr).validate_python(email.strip().lower()))
    try:
        async with get_session_factory()() as session:
            repository = AdminRepository(session)
            existing = await repository.get_by_email(normalized_email)
            if existing is not None:
                raise SystemExit("Un compte existe déjà avec cet email.")
            user = User(
                email=normalized_email,
                password_hash=hash_password(password),
                role=UserRole.SUPER_ADMIN,
                is_active=True,
            )
            created = await repository.create(user)
            await repository.add_audit_log(
                created.id,
                AdminAuditAction.ADMIN_CREATED,
                created.id,
                None,
            )
            await repository.commit()
            print(f"Super administrateur créé : {normalized_email}")
    finally:
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser("create-super-admin")
    create_parser.add_argument("--email")
    create_parser.add_argument("--password")
    args = parser.parse_args()

    email = args.email or os.getenv("SUPER_ADMIN_EMAIL")
    password = args.password or os.getenv("SUPER_ADMIN_PASSWORD")
    if not email or not password:
        parser.error(
            "Email et mot de passe requis via --email/--password "
            "ou SUPER_ADMIN_EMAIL/SUPER_ADMIN_PASSWORD."
        )

    try:
        asyncio.run(create_super_admin(email, password))
    except ValidationError as exc:
        parser.error(f"Email invalide : {exc}")


if __name__ == "__main__":
    main()
