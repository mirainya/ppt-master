"""Create the first database-backed PPT Master administrator.

Usage:
    python -m service.admin create --username admin
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os

import asyncpg

from service.auth import hash_password, normalize_username
from service.auth_repository import AuthRepository
from service.config import Settings
from service.database import Database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage PPT Master administrators.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser("create", help="create an administrator")
    create_parser.add_argument("--username", required=True)
    create_parser.add_argument(
        "--password-env",
        default="PPT_ADMIN_PASSWORD",
        help="environment variable containing the password",
    )
    return parser


async def create_administrator(username: str, password: str) -> None:
    settings = Settings.from_env()
    database = Database(settings.database_url)
    await database.connect()
    try:
        repository = AuthRepository(database)
        await repository.create_user(
            normalize_username(username),
            hash_password(password),
            is_admin=True,
        )
    finally:
        await database.close()


def main() -> int:
    args = build_parser().parse_args()
    password = os.environ.get(args.password_env) or getpass.getpass("Password: ")
    try:
        asyncio.run(create_administrator(args.username, password))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    except asyncpg.UniqueViolationError as exc:
        raise SystemExit("username already exists") from exc
    print(f"Created administrator {normalize_username(args.username)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
