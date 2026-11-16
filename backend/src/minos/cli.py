"""Administrative commands.

    python -m minos.cli migrate                      # apply database migrations
    python -m minos.cli create-admin-key --name ops  # print a new global admin API key

Both read ``MINOS_DATABASE_URL``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

from minos.control import service as svc
from minos.db import make_engine, make_sessionmaker
from minos.settings import Settings

MIGRATIONS = Path(__file__).resolve().parent / "db" / "migrations"


def alembic_config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.cmd_opts = argparse.Namespace(x=[f"url={url}"])
    return cfg


def migrate(url: str, revision: str = "head") -> None:
    command.upgrade(alembic_config(url), revision)


async def create_admin_key(url: str, name: str) -> str:
    engine = make_engine(url)
    try:
        async with make_sessionmaker(engine).begin() as s:
            _, key = await svc.create_api_client(s, "cli", None, name, ["admin"])
    finally:
        await engine.dispose()
    return key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="minos")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="apply database migrations")
    key = sub.add_parser("create-admin-key", help="create a global admin API key")
    key.add_argument("--name", required=True)
    args = parser.parse_args(argv)

    url = Settings.from_env().database_url
    if not url:
        print("MINOS_DATABASE_URL is not set", file=sys.stderr)
        return 2
    if args.cmd == "migrate":
        migrate(url)
        print("database is up to date")
    else:
        print(asyncio.run(create_admin_key(url, args.name)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
