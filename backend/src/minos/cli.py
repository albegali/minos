"""Administrative commands.

    python -m minos.cli migrate                      # apply database migrations
    python -m minos.cli create-admin-key --name ops  # print a new global admin API key
    python -m minos.cli seed-examples                # load the examples into workspace "esempi"

All read ``MINOS_DATABASE_URL``. ``seed-examples`` reads the examples from ``--dir``, else
``MINOS_EXAMPLES_DIR``, else the repository's ``examples`` directory; it does nothing when the
workspace already exists.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

from minos.control import service as svc
from minos.control.examples import WORKSPACE, load_examples, seed_examples
from minos.db import make_engine, make_sessionmaker
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


async def seed(url: str, root: Path, workspace: str) -> list[str] | None:
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
        published = asyncio.run(seed(url, root, args.workspace))
        if published is None:
            print(f"workspace {args.workspace!r} already exists: examples not loaded")
        else:
            print(f"workspace {args.workspace!r}: published {', '.join(published)} in prod")
    else:
        print(asyncio.run(create_admin_key(url, args.name)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
