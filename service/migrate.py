"""Apply tracked PostgreSQL migrations for the PPT Master API.

Usage:
    python -m service.migrate --show
    python -m service.migrate --apply --confirm APPLY
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import asyncpg

from service.config import Settings


MIGRATION_DIR = Path(__file__).resolve().parent.parent / "database" / "migrations"


def migration_files() -> list[Path]:
    """Return migrations in filename order."""
    return sorted(MIGRATION_DIR.glob("*.sql"))


def show_migrations() -> None:
    """Print complete migration SQL without connecting to PostgreSQL."""
    for path in migration_files():
        print(f"-- Migration: {path.name}")
        print(path.read_text(encoding="utf-8").rstrip())
        print()


async def apply_migrations(database_url: str) -> None:
    """Apply each pending migration once inside a transaction."""
    connection = await asyncpg.connect(database_url)
    try:
        await connection.execute("SELECT pg_advisory_lock(781245907)")
        table_exists = await connection.fetchval(
            "SELECT to_regclass('public.schema_migrations')"
        )
        applied = set()
        if table_exists is not None:
            rows = await connection.fetch("SELECT version FROM schema_migrations")
            applied = {row["version"] for row in rows}

        applied_now = 0
        for path in migration_files():
            if path.name in applied:
                continue
            sql = path.read_text(encoding="utf-8")
            async with connection.transaction():
                await connection.execute(sql)
                await connection.execute(
                    "INSERT INTO schema_migrations (version) VALUES ($1)",
                    path.name,
                )
            print(f"Applied {path.name}")
            applied_now += 1
        if applied_now == 0:
            # Say so explicitly: silence here is ambiguous between "already up to
            # date" and "the file never made it into this image".
            print("No pending migrations")
    finally:
        try:
            await connection.execute("SELECT pg_advisory_unlock(781245907)")
        finally:
            await connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage PPT Master API database migrations."
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--show", action="store_true", help="print complete migration SQL"
    )
    action.add_argument("--apply", action="store_true", help="apply pending migrations")
    parser.add_argument(
        "--confirm",
        help="required confirmation token for --apply; must be APPLY",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.show:
        show_migrations()
        return 0
    if args.confirm != "APPLY":
        raise SystemExit(
            "--apply requires --confirm APPLY after reviewing --show output"
        )
    settings = Settings.from_env()
    asyncio.run(apply_migrations(settings.database_url))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
