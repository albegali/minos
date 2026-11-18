from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import asyncpg
import pytest

from minos.cli import migrate

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"


# Host names the test clients use: allowed like localhost (see Settings.allowed_hosts).
TEST_HOSTS = ("localhost", "127.0.0.1", "::1", "testserver", "m", "minos")


@pytest.fixture(autouse=True)
def _test_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINOS_ALLOWED_HOSTS", "testserver,m,minos")


def load_json(relative: str) -> Any:
    return json.loads((EXAMPLES / relative).read_text())


@pytest.fixture
def aurora_graph() -> dict[str, Any]:
    data: dict[str, Any] = load_json("rulesets/aurora.studyplan.emba.json")
    return data


@pytest.fixture
def valid_plan() -> dict[str, Any]:
    data: dict[str, Any] = load_json("inputs/studyplan-emba-valid.json")
    return data


@pytest.fixture
def invalid_plan() -> dict[str, Any]:
    data: dict[str, Any] = load_json("inputs/studyplan-emba-invalid.json")
    return data


def graph(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    """Minimal RGD wrapper used by the unit tests."""
    doc: dict[str, Any] = {"rgdVersion": "1.0", "ruleset": "t.test", "nodes": nodes, "edges": edges}
    doc.update(extra)
    return doc


# --------------------------------------------------------------------------- database fixtures

TEST_DB_URL = os.environ.get(
    "MINOS_TEST_DATABASE_URL", "postgresql+asyncpg://minos:minos@localhost:5432/minos_test"
)


async def _recreate_database(url: str) -> None:
    dsn = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    base, _, name = dsn.rpartition("/")
    conn = await asyncpg.connect(f"{base}/postgres")
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def database_url() -> str:
    """A freshly migrated test database; DB tests are skipped if PostgreSQL is unavailable."""
    try:
        asyncio.run(_recreate_database(TEST_DB_URL))
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"PostgreSQL not available: {exc}")
    migrate(TEST_DB_URL)
    return TEST_DB_URL


TABLES = (
    "audit_event, user_session, invitation, workspace_member, org_member, user_email, app_user, "
    "api_client, test_case, ruleset_alias, ruleset_version, ruleset_draft, "
    "ruleset, schema_version, entity, workspace, organization"
)


@pytest.fixture
async def clean_db(database_url: str) -> AsyncIterator[str]:
    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE")
        # the organization the migration creates for workspaces created without one
        await conn.execute(
            "INSERT INTO organization (id, slug, name) "
            "VALUES ('00000000-0000-0000-0000-000000000001', 'default', 'Default')"
        )
    finally:
        await conn.close()
    yield database_url
