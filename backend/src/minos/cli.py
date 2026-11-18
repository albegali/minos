"""Administrative commands.

    python -m minos.cli migrate                      # apply database migrations
    python -m minos.cli create-admin-key --name ops  # print a new global admin API key
    python -m minos.cli list-admin-keys              # global admin API keys
    python -m minos.cli revoke-key <id>              # revoke any API key (admin or workspace)
    python -m minos.cli seed-examples                # load the examples into workspace "esempi"
    python -m minos.cli create-organization --slug gsom --name "GSoM"
    python -m minos.cli create-user --email a@x.it --name "Ada" --organization gsom --role owner
    python -m minos.cli prune-audit [--days 90] [--all]  # audit retention

All read ``MINOS_DATABASE_URL``. ``create-user`` reads the password from ``MINOS_PASSWORD`` or
asks for it; for an address that already has an account it only adds the membership.
``seed-examples`` reads the examples from ``--dir``, else ``MINOS_EXAMPLES_DIR``, else the
repository's ``examples`` directory; it only adds the examples the workspace lacks, leaving
existing entities and rule sets alone.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import getpass
import os
import sys
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from minos.control import accounts
from minos.control import service as svc
from minos.control.errors import ControlError
from minos.control.examples import WORKSPACE, Seeded, load_examples, seed_examples
from minos.control.identity import CLI, ORG_ROLES
from minos.db import ApiClient, Workspace, make_engine, make_sessionmaker
from minos.settings import Settings

MIGRATIONS = Path(__file__).resolve().parent / "db" / "migrations"
REPO_EXAMPLES = Path(__file__).resolve().parents[3] / "examples"
SEED_LOCK = 0x4D494E4F5345  # "MINOSE"


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
            _, key = await svc.create_api_client(s, CLI, None, name, ["admin"])
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
            await svc.revoke_api_client(s, CLI, ws, key_id)
    finally:
        await engine.dispose()
    return True


async def create_organization(url: str, slug: str, name: str) -> None:
    engine = make_engine(url)
    try:
        async with make_sessionmaker(engine).begin() as s:
            await accounts.create_organization(s, CLI, slug, name)
    finally:
        await engine.dispose()


async def create_user(
    url: str,
    email: str,
    name: str,
    password: str | None,
    organization: str | None,
    role: str,
) -> bool:
    """Create an account (or reuse the one of ``email``) and add it to ``organization``;
    returns whether the account is new."""
    engine = make_engine(url)
    try:
        async with make_sessionmaker(engine).begin() as s:
            user = await accounts.find_user(s, email)
            created = user is None
            if user is None:
                user = await accounts.create_user(s, email, name, password)
            if organization:
                org = await accounts.get_organization(s, organization)
                await accounts.add_member(s, CLI, org, user, role)
    finally:
        await engine.dispose()
    return created


async def prune_audit(url: str, days: float, everything: bool) -> int:
    engine = make_engine(url)
    try:
        async with make_sessionmaker(engine).begin() as s:
            return await svc.prune_audit(
                s, dt.timedelta(days=days), None if everything else ("draft.save",)
            )
    finally:
        await engine.dispose()


async def seed(url: str, root: Path, workspace: str) -> Seeded:
    examples = load_examples(root)
    engine = make_engine(url)
    try:
        async with make_sessionmaker(engine).begin() as s:
            # one replica at a time (they all seed on start)
            await s.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": SEED_LOCK})
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
    org = sub.add_parser("create-organization", help="create an organization")
    org.add_argument("--slug", required=True)
    org.add_argument("--name", required=True)
    user = sub.add_parser("create-user", help="create a user, optionally in an organization")
    user.add_argument("--email", required=True)
    user.add_argument("--name", required=True)
    user.add_argument("--organization")
    user.add_argument("--role", choices=ORG_ROLES, default="member")
    prune = sub.add_parser("prune-audit", help="delete old draft-save audit events")
    prune.add_argument("--days", type=float, help="default: MINOS_AUDIT_RETENTION_DAYS (90)")
    prune.add_argument("--all", action="store_true", help="every kind of event, not only drafts")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    url = settings.database_url
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
    elif args.cmd in ("create-organization", "create-user"):
        try:
            if args.cmd == "create-organization":
                asyncio.run(create_organization(url, args.slug, args.name))
                print(f"organization {args.slug!r} created")
            else:
                password = os.environ.get("MINOS_PASSWORD") or getpass.getpass("Password: ")
                created = asyncio.run(
                    create_user(url, args.email, args.name, password, args.organization, args.role)
                )
                print(f"user {args.email} {'created' if created else 'already exists'}")
        except ControlError as exc:
            print(exc.detail, file=sys.stderr)
            return 1
    elif args.cmd == "prune-audit":
        days = args.days if args.days is not None else settings.audit_retention_days
        removed = asyncio.run(prune_audit(url, days, args.all))
        print(f"{removed} audit event(s) older than {days:g} days removed")
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
