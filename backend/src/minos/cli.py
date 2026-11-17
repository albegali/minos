"""Administrative commands.

    python -m minos.cli migrate                      # apply database migrations
    python -m minos.cli create-admin-key --name ops  # print a new global admin API key
    python -m minos.cli list-admin-keys              # global admin API keys
    python -m minos.cli revoke-key <id>              # revoke any API key (admin or workspace)
    python -m minos.cli seed-examples                # load the examples into workspace "esempi"

All read ``MINOS_DATABASE_URL``. ``seed-examples`` reads the examples from ``--dir``, else
``MINOS_EXAMPLES_DIR``, else the repository's ``examples`` directory; it only adds the examples
the workspace lacks, leaving existing entities and rule sets alone.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config

from minos.control import service as svc
from minos.control.examples import WORKSPACE, Seeded, load_examples, seed_examples
from minos.db import ApiClient, Workspace, make_engine, make_sessionmaker
from minos.settings import Settings

MIGRATIONS = Path(__file__).resolve().parent / "db" / "migrations"
REPO_EXAMPLES = Path(__file__).resolve().parents[3] / "examples"


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


async def list_admin_keys(url: str) -> list[str]:
    engine = make_engine(url)
    try:
        async with make_sessionmaker(engine)() as s:
            clients = await svc.list_api_clients(s, None)
    finally:
        await engine.dispose()
    return [
        f"{c.id}  {c.key_prefix}  {c.name}  {'revoked' if c.revoked_at else 'active'}"
        for c in clients
    ]


async def revoke_key(url: str, key_id: uuid.UUID) -> bool:
    """Revoke any key by id (the CLI has database access, so no scope applies)."""
    engine = make_engine(url)
    try:
        async with make_sessionmaker(engine).begin() as s:
            client = await s.get(ApiClient, key_id)
            if client is None:
                return False
            ws = await s.get(Workspace, client.workspace_id) if client.workspace_id else None
            await svc.revoke_api_client(s, "cli", ws, key_id)
    finally:
        await engine.dispose()
    return True


async def seed(url: str, root: Path, workspace: str) -> Seeded:
    examples = load_examples(root)
    engine = make_engine(url)
    try:
        async with make_sessionmaker(engine).begin() as s:
            return await seed_examples(s, examples, workspace)
    finally:
        await engine.dispose()


def examples_dir(value: str | None) -> Path:
    return Path(value or os.environ.get("MINOS_EXAMPLES_DIR") or REPO_EXAMPLES)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="minos")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="apply database migrations")
    key = sub.add_parser("create-admin-key", help="create a global admin API key")
    key.add_argument("--name", required=True)
    sub.add_parser("list-admin-keys", help="list the global admin API keys")
    revoke = sub.add_parser("revoke-key", help="revoke an API key (admin or workspace) by id")
    revoke.add_argument("id", type=uuid.UUID)
    examples = sub.add_parser("seed-examples", help="load the examples into a new workspace")
    examples.add_argument("--dir", help="examples directory (rulesets/, inputs/, tests/)")
    examples.add_argument("--workspace", default=WORKSPACE)
    args = parser.parse_args(argv)

    url = Settings.from_env().database_url
    if not url:
        print("MINOS_DATABASE_URL is not set", file=sys.stderr)
        return 2
    if args.cmd == "migrate":
        migrate(url)
        print("database is up to date")
    elif args.cmd == "seed-examples":
        root = examples_dir(args.dir)
        if not (root / "rulesets").is_dir():
            print(f"no examples in {root}", file=sys.stderr)
            return 2
        seeded = asyncio.run(seed(url, root, args.workspace))
        for reason in seeded.skipped:
            print(f"example skipped: {reason}", file=sys.stderr)
        if not seeded.published:
            print(f"workspace {args.workspace!r}: nothing to add")
        else:
            print(f"workspace {args.workspace!r}: published {', '.join(seeded.published)} in prod")
    elif args.cmd == "list-admin-keys":
        for line in asyncio.run(list_admin_keys(url)):
            print(line)
    elif args.cmd == "revoke-key":
        if not asyncio.run(revoke_key(url, args.id)):
            print(f"no API key {args.id}", file=sys.stderr)
            return 1
        print(f"API key {args.id} revoked")
    else:
        print(asyncio.run(create_admin_key(url, args.name)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
