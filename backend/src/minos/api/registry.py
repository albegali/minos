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
import datetime as dt
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
from minos.control.service import resolver_for, resolver_from
from minos.db import (
    ALWAYS,
    NOTIFY_CHANNEL,
    ApiClient,
    Ruleset,
    RulesetAlias,
    RulesetVersion,
    SchemaVersion,
    Workspace,
)
from minos.engine import CompiledRuleset, compile_ruleset
from minos.engine.compiler import Resolver
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


def build(
    workspace: str,
    graph: dict[str, Any],
    schema: dict[str, Any] | None,
    resolve: Resolver | None = None,
) -> Deployment:
    # Published graphs were type-checked at publish time; recompiling with the schema keeps
    # the guarantee if a version is loaded by a newer engine.
    compiled = compile_ruleset(graph, schema, resolve)
    return Deployment(workspace, compiled, InputValidator(schema) if schema else None)


type Schedule = tuple[tuple[dt.date, Deployment], ...]
"""Entries of one environment, sorted by start date (``ALWAYS`` first)."""


def pick(schedule: Schedule, on: dt.date) -> Deployment | None:
    """The deployment of the latest entry starting on or before ``on``."""
    for start, deployment in reversed(schedule):
        if start <= on:
            return deployment
    return None


class RulesetRegistry:
    def __init__(self) -> None:
        self._schedules: dict[Key, Schedule] = {}
        self._versions: dict[Key, Deployment] = {}
        self.ready = False

    # ------------------------------------------------------------------ lookups (hot path)

    def get(
        self, workspace: str, ruleset: str, env: str = DEFAULT_ENV, on: dt.date | None = None
    ) -> Deployment | None:
        schedule = self._schedules.get((workspace, ruleset, env))
        if schedule is None:
            return None
        return pick(schedule, on or dt.datetime.now(dt.UTC).date())

    def get_version(self, workspace: str, ruleset: str, semver: str) -> Deployment | None:
        return self._versions.get((workspace, ruleset, semver))

    # ------------------------------------------------------------------ updates

    def all(self) -> list[tuple[Key, dt.date, Deployment]]:
        return [
            (key, start, dep)
            for key, schedule in sorted(self._schedules.items())
            for start, dep in schedule
        ]

    def schedules(self) -> dict[Key, Schedule]:
        return dict(self._schedules)

    def put(self, key: Key, schedule: Schedule | None) -> None:
        updated = dict(self._schedules)
        if not schedule:
            updated.pop(key, None)
        else:
            updated[key] = tuple(sorted(schedule, key=lambda e: e[0]))
        self._schedules = updated  # atomic swap

    def replace_all(
        self, schedules: dict[Key, Schedule], keep_workspace: str | None = None
    ) -> None:
        """Replace every schedule, except those of ``keep_workspace`` (file-served ones)."""
        kept = {k: v for k, v in self._schedules.items() if k[0] == keep_workspace}
        fresh = {k: tuple(sorted(v, key=lambda e: e[0])) for k, v in schedules.items()}
        self._schedules = {**fresh, **kept}

    def put_version(self, key: Key, deployment: Deployment) -> None:
        if len(self._versions) > 1000:  # bounded: fixed-version calls are the exception
            self._versions = {}
        self._versions[key] = deployment

    def load_directory(self, directory: Path) -> int:
        """Serve every RGD file of ``directory``; sub-rulesets resolve among the same files by
        ``ruleset`` and ``version``."""
        graphs = [orjson.loads(f.read_bytes()) for f in sorted(directory.glob("*.json"))]
        resolve = resolver_from(
            {(g["ruleset"], g.get("version", "0.0.0")): (g, None) for g in graphs}
        )
        count = 0
        for file, graph in zip(sorted(directory.glob("*.json")), graphs, strict=True):
            dep = build(LOCAL_WORKSPACE, graph, None, resolve)
            for warning in dep.compiled.warnings:
                log.warning("%s: %s", file.name, warning)
            self.put((LOCAL_WORKSPACE, dep.compiled.ruleset, DEFAULT_ENV), ((ALWAYS, dep),))
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
        RulesetAlias.effective_from,
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
    select(
        Workspace.slug,
        Ruleset.key,
        RulesetAlias.env,
        RulesetAlias.effective_from,
        RulesetVersion.hash,
    )
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
        grouped: dict[Key, list[Any]] = {}
        for row in rows:
            grouped.setdefault((row.slug, row.key, row.env), []).append(row)
        schedules: dict[Key, Schedule] = {}
        for key, entries in grouped.items():
            try:
                schedules[key] = await self._schedule(key[0], entries)
            except Exception:  # a broken version must not take the others down
                log.exception("cannot load %s/%s@%s", *key)
        # Rule sets served from files (workspace "local") are not managed by the database.
        self.registry.replace_all(schedules, keep_workspace=LOCAL_WORKSPACE)
        self.reloads += 1
        log.info("loaded %d deployments", len(schedules))

    async def _schedule(self, ws: str, entries: list[Any]) -> Schedule:
        out = []
        for row in entries:
            async with self.sessions() as s:
                resolve = await resolver_for(s, ws, row.graph)
            out.append((row.effective_from, build(ws, row.graph, row.json_schema, resolve)))
        return tuple(out)

    async def reload_one(self, ws: str, rs: str, env: str) -> None:
        q = _ALIAS_QUERY.where(Workspace.slug == ws, Ruleset.key == rs, RulesetAlias.env == env)
        async with self.sessions() as s:
            rows = (await s.execute(q)).all()
        self.registry.put((ws, rs, env), await self._schedule(ws, list(rows)) if rows else None)
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
        async with self.sessions() as s:
            resolve = await resolver_for(s, ws, row.graph)
        dep = build(ws, row.graph, row.json_schema, resolve)
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
        """Reload environments whose entries differ from the database; return how many."""
        async with self.sessions() as s:
            rows = (await s.execute(_HASH_QUERY)).all()
        wanted: dict[Key, list[tuple[dt.date, str]]] = {}
        for ws, rs, env, start, digest in rows:
            wanted.setdefault((ws, rs, env), []).append((start, digest))
        current = {
            key: sorted((start, dep.hash) for start, dep in schedule)
            for key, schedule in self.registry.schedules().items()
            if key[0] != LOCAL_WORKSPACE
        }
        stale = [k for k, v in wanted.items() if current.get(k) != sorted(v)]
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
