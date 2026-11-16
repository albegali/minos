"""In-memory registry of deployed rule sets for the execution API.

Deployments are keyed by ``(workspace, ruleset, env)`` and replaced with an atomic dict swap,
so in-flight requests finish on the version they started with. Fixed versions requested by
semver are loaded lazily and cached (published versions are immutable).

Sources:

* :meth:`RulesetRegistry.load_directory` — RGD files served as workspace ``local``, env
  ``prod`` (development / offline);
* :class:`DbSync` — PostgreSQL: initial load, ``LISTEN`` on :data:`NOTIFY_CHANNEL` for
  changes, and a periodic hash comparison as a safety net for missed notifications.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import asyncpg
import orjson
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from minos.api.common import Principal
from minos.db import (
    NOTIFY_CHANNEL,
    ApiClient,
    Ruleset,
    RulesetAlias,
    RulesetVersion,
    SchemaVersion,
    Workspace,
)
from minos.engine import CompiledRuleset, compile_ruleset
from minos.schema import InputValidator

log = logging.getLogger(__name__)

LOCAL_WORKSPACE = "local"
DEFAULT_ENV = "prod"

type Key = tuple[str, str, str]  # workspace, ruleset, env | semver


@dataclass(frozen=True, slots=True)
class Deployment:
    workspace: str
    compiled: CompiledRuleset
    validator: InputValidator | None

    @property
    def hash(self) -> str:
        return self.compiled.hash


def build(workspace: str, graph: dict[str, Any], schema: dict[str, Any] | None) -> Deployment:
    # Published graphs were type-checked at publish time; recompiling with the schema keeps
    # the guarantee if a version is loaded by a newer engine.
    compiled = compile_ruleset(graph, schema)
    return Deployment(workspace, compiled, InputValidator(schema) if schema else None)


class RulesetRegistry:
    def __init__(self) -> None:
        self._deployments: dict[Key, Deployment] = {}
        self._versions: dict[Key, Deployment] = {}
        self.ready = False

    # ------------------------------------------------------------------ lookups (hot path)

    def get(self, workspace: str, ruleset: str, env: str = DEFAULT_ENV) -> Deployment | None:
        return self._deployments.get((workspace, ruleset, env))

    def get_version(self, workspace: str, ruleset: str, semver: str) -> Deployment | None:
        return self._versions.get((workspace, ruleset, semver))

    # ------------------------------------------------------------------ updates

    def all(self) -> list[tuple[Key, Deployment]]:
        return sorted(self._deployments.items())

    def put(self, key: Key, deployment: Deployment | None) -> None:
        updated = dict(self._deployments)
        if deployment is None:
            updated.pop(key, None)
        else:
            updated[key] = deployment
        self._deployments = updated  # atomic swap

    def replace_all(self, deployments: dict[Key, Deployment]) -> None:
        self._deployments = dict(deployments)

    def put_version(self, key: Key, deployment: Deployment) -> None:
        if len(self._versions) > 1000:  # bounded: fixed-version calls are the exception
            self._versions = {}
        self._versions[key] = deployment

    def load_directory(self, directory: Path) -> int:
        count = 0
        for file in sorted(directory.glob("*.json")):
            graph = orjson.loads(file.read_bytes())
            dep = build(LOCAL_WORKSPACE, graph, None)
            for warning in dep.compiled.warnings:
                log.warning("%s: %s", file.name, warning)
            self.put((LOCAL_WORKSPACE, dep.compiled.ruleset, DEFAULT_ENV), dep)
            count += 1
        return count


class KeyCache:
    """API key -> principal, cached so the execution hot path rarely touches the database."""

    def __init__(self, ttl_s: float = 60.0, negative_ttl_s: float = 5.0) -> None:
        self.ttl_s = ttl_s
        self.negative_ttl_s = negative_ttl_s
        self._items: dict[str, tuple[Principal | None, float]] = {}

    def get(self, key_hash: str) -> tuple[bool, Principal | None]:
        hit = self._items.get(key_hash)
        if hit is None or hit[1] < time.monotonic():
            return False, None
        return True, hit[0]

    def put(self, key_hash: str, principal: Principal | None) -> None:
        ttl = self.ttl_s if principal else self.negative_ttl_s
        if len(self._items) > 10_000:
            self._items = {}
        self._items[key_hash] = (principal, time.monotonic() + ttl)

    def evict(self, key_hash: str) -> None:
        self._items.pop(key_hash, None)


_ALIAS_QUERY = (
    select(
        Workspace.slug,
        Ruleset.key,
        RulesetAlias.env,
        RulesetVersion.hash,
        RulesetVersion.graph,
        SchemaVersion.json_schema,
    )
    .join(Ruleset, Ruleset.workspace_id == Workspace.id)
    .join(RulesetAlias, RulesetAlias.ruleset_id == Ruleset.id)
    .join(RulesetVersion, RulesetVersion.id == RulesetAlias.version_id)
    .outerjoin(SchemaVersion, SchemaVersion.id == RulesetVersion.schema_version_id)
)

_HASH_QUERY = (
    select(Workspace.slug, Ruleset.key, RulesetAlias.env, RulesetVersion.hash)
    .join(Ruleset, Ruleset.workspace_id == Workspace.id)
    .join(RulesetAlias, RulesetAlias.ruleset_id == Ruleset.id)
    .join(RulesetVersion, RulesetVersion.id == RulesetAlias.version_id)
)


class DbSync:
    """Keeps a :class:`RulesetRegistry` in sync with PostgreSQL."""

    def __init__(
        self,
        registry: RulesetRegistry,
        keys: KeyCache,
        sessions: async_sessionmaker[AsyncSession],
        dsn: str,
        poll_interval_s: float,
    ) -> None:
        self.registry = registry
        self.keys = keys
        self.sessions = sessions
        self.dsn = dsn
        self.poll_interval_s = poll_interval_s
        self._listener: asyncpg.Connection | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self.reloads = 0  # observable in tests and metrics

    async def start(self) -> None:
        await self.load_all()
        await self._listen()
        self._tasks.append(asyncio.create_task(self._poll_forever(), name="minos-poll"))
        self.registry.ready = True

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if self._listener is not None:
            await self._listener.close()

    # ------------------------------------------------------------------ loading

    async def load_all(self) -> None:
        async with self.sessions() as s:
            rows = (await s.execute(_ALIAS_QUERY)).all()
        deployments: dict[Key, Deployment] = {}
        for ws, rs, env, _hash, graph, schema in rows:
            try:
                deployments[(ws, rs, env)] = build(ws, graph, schema)
            except Exception:  # a broken version must not take the others down
                log.exception("cannot load %s/%s@%s", ws, rs, env)
        self.registry.replace_all(deployments)
        self.reloads += 1
        log.info("loaded %d deployments", len(deployments))

    async def reload_one(self, ws: str, rs: str, env: str) -> None:
        q = _ALIAS_QUERY.where(Workspace.slug == ws, Ruleset.key == rs, RulesetAlias.env == env)
        async with self.sessions() as s:
            row = (await s.execute(q)).first()
        if row is None:
            self.registry.put((ws, rs, env), None)
        else:
            self.registry.put((ws, rs, env), build(ws, row.graph, row.json_schema))
        self.reloads += 1

    async def load_version(self, ws: str, rs: str, semver: str) -> Deployment | None:
        cached = self.registry.get_version(ws, rs, semver)
        if cached is not None:
            return cached
        q = (
            select(RulesetVersion.graph, SchemaVersion.json_schema)
            .join(Ruleset, Ruleset.id == RulesetVersion.ruleset_id)
            .join(Workspace, Workspace.id == Ruleset.workspace_id)
            .outerjoin(SchemaVersion, SchemaVersion.id == RulesetVersion.schema_version_id)
            .where(Workspace.slug == ws, Ruleset.key == rs, RulesetVersion.semver == semver)
        )
        async with self.sessions() as s:
            row = (await s.execute(q)).first()
        if row is None:
            return None
        dep = build(ws, row.graph, row.json_schema)
        self.registry.put_version((ws, rs, semver), dep)
        return dep

    async def authenticate(self, key: str, key_hash: str) -> Principal | None:
        hit, principal = self.keys.get(key_hash)
        if hit:
            return principal
        q = (
            select(ApiClient.name, ApiClient.workspace_id, ApiClient.scopes, Workspace.slug)
            .outerjoin(Workspace, Workspace.id == ApiClient.workspace_id)
            .where(ApiClient.key_hash == key_hash, ApiClient.revoked_at.is_(None))
        )
        async with self.sessions() as s:
            row = (await s.execute(q)).first()
        if row is not None:
            principal = Principal(row.name, row.workspace_id, frozenset(row.scopes), row.slug)
        self.keys.put(key_hash, principal)
        return principal

    # ------------------------------------------------------------------ notifications

    async def _listen(self) -> None:
        try:
            self._listener = await asyncpg.connect(self.dsn)
            await self._listener.add_listener(NOTIFY_CHANNEL, self._on_notify)
        except OSError, asyncpg.PostgresError:
            log.exception("LISTEN failed; relying on polling until the next attempt")
            self._listener = None

    def _on_notify(self, _conn: Any, _pid: int, _channel: str, payload: str) -> None:
        try:
            event = json.loads(payload)
        except ValueError:
            return
        if event.get("kind") == "alias":
            self._spawn(self.reload_one(event["workspace"], event["ruleset"], event["env"]))
        elif event.get("kind") == "apikey":
            self.keys.evict(event.get("keyHash", ""))

    def _spawn(self, coro: Any) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.append(task)
        task.add_done_callback(self._forget)

    def _forget(self, task: asyncio.Task[None]) -> None:
        with contextlib.suppress(ValueError):
            self._tasks.remove(task)
        if not task.cancelled() and task.exception() is not None:
            log.error("reload failed", exc_info=task.exception())

    # ------------------------------------------------------------------ safety net

    async def check_drift(self) -> int:
        """Reload deployments whose hash differs from the database; return how many."""
        async with self.sessions() as s:
            rows = (await s.execute(_HASH_QUERY)).all()
        wanted = {(ws, rs, env): h for ws, rs, env, h in rows}
        current = {k: d.hash for k, d in self.registry.all()}
        stale = [k for k, h in wanted.items() if current.get(k) != h]
        gone = [k for k in current if k not in wanted]
        for ws, rs, env in stale:
            await self.reload_one(ws, rs, env)
        for key in gone:
            self.registry.put(key, None)
        return len(stale) + len(gone)

    async def _poll_forever(self) -> None:
        while True:
            await asyncio.sleep(self.poll_interval_s)
            try:
                drift = await self.check_drift()
                if drift:
                    log.warning("polling fixed %d stale deployment(s)", drift)
                if self._listener is None or self._listener.is_closed():
                    await self._listen()
            except Exception:
                log.exception("polling failed")
