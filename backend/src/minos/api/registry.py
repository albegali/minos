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
from typing import Any, Final

import asyncpg
import orjson
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from minos.api.common import Principal
from minos.control.keys import well_formed
from minos.control.service import qualified_name, resolver_for, resolver_from, split_name
from minos.db import (
    ALWAYS,
    NOTIFY_CHANNEL,
    ApiClient,
    Organization,
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

type Key = tuple[str, str, str]  # workspace (qualified name), ruleset, env | semver
"""Workspaces are named as in :func:`minos.control.service.qualified_name`: the slug in the
``default`` organization, ``<org>/<slug>`` in the others."""


@dataclass(frozen=True, slots=True)
class Deployment:
    workspace: str
    compiled: CompiledRuleset
    validator: InputValidator | None
    schema: dict[str, Any] | None = None
    """Entity schema the version was published against (documents the execution API)."""
    feedback_codes: tuple[tuple[str, str], ...] = ()
    """``(code, severity)`` of the feedback the graph itself declares, in order of appearance."""

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
    return Deployment(
        workspace,
        compiled,
        InputValidator(schema) if schema else None,
        schema,
        declared_feedback(graph),
    )


def declared_feedback(graph: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    """Feedback codes declared anywhere in the graph's nodes (sub-rule sets not included)."""
    found: dict[str, str] = {}

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            code = value.get("code")
            if isinstance(code, str) and "message" in value:
                found.setdefault(code, str(value.get("severity", "error")))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(graph.get("nodes", []))
    return tuple(found.items())


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
        self.generation = 0
        """Bumped on every change of the deployed schedules (cache key for derived documents)."""

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
        self.generation += 1

    def replace_all(
        self, schedules: dict[Key, Schedule], keep_workspace: str | None = None
    ) -> None:
        """Replace every schedule, except those of ``keep_workspace`` (file-served ones)."""
        kept = {k: v for k, v in self._schedules.items() if k[0] == keep_workspace}
        fresh = {k: tuple(sorted(v, key=lambda e: e[0])) for k, v in schedules.items()}
        self._schedules = {**fresh, **kept}
        self.generation += 1

    def drop_version(self, key: Key) -> None:
        self._versions.pop(key, None)

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

    MAX_ENTRIES: Final = 10_000

    def __init__(self, ttl_s: float = 60.0, negative_ttl_s: float = 5.0) -> None:
        self.ttl_s = ttl_s
        self.negative_ttl_s = negative_ttl_s
        # Valid and unknown keys are kept apart: a flood of unknown keys can only push out
        # other unknown keys, never the valid ones.
        self._valid: dict[str, tuple[Principal, float]] = {}
        self._unknown: dict[str, float] = {}

    def get(self, key_hash: str) -> tuple[bool, Principal | None]:
        now = time.monotonic()
        hit = self._valid.get(key_hash)
        if hit is not None and hit[1] >= now:
            return True, hit[0]
        expires = self._unknown.get(key_hash)
        if expires is not None and expires >= now:
            return True, None
        return False, None

    def put(self, key_hash: str, principal: Principal | None) -> None:
        now = time.monotonic()
        if principal is not None:
            _bounded_put(self._valid, key_hash, (principal, now + self.ttl_s), self.MAX_ENTRIES)
        else:
            _bounded_put(self._unknown, key_hash, now + self.negative_ttl_s, self.MAX_ENTRIES)

    def evict(self, key_hash: str) -> None:
        self._valid.pop(key_hash, None)
        self._unknown.pop(key_hash, None)


def _bounded_put[V](items: dict[str, V], key: str, value: V, limit: int) -> None:
    items.pop(key, None)
    while len(items) >= limit:
        items.pop(next(iter(items)))  # oldest first
    items[key] = value


_ALIAS_QUERY = (
    select(
        Organization.slug.label("org"),
        Workspace.slug,
        Workspace.id.label("workspace_id"),
        Ruleset.key,
        RulesetAlias.env,
        RulesetAlias.effective_from,
        RulesetVersion.hash,
        RulesetVersion.graph,
        SchemaVersion.resolved_schema,
    )
    .join(Organization, Organization.id == Workspace.organization_id)
    .join(Ruleset, Ruleset.workspace_id == Workspace.id)
    .join(RulesetAlias, RulesetAlias.ruleset_id == Ruleset.id)
    .join(RulesetVersion, RulesetVersion.id == RulesetAlias.version_id)
    .outerjoin(SchemaVersion, SchemaVersion.id == RulesetVersion.schema_version_id)
)

_HASH_QUERY = (
    select(
        Organization.slug.label("org"),
        Workspace.slug,
        Ruleset.key,
        RulesetAlias.env,
        RulesetAlias.effective_from,
        RulesetVersion.hash,
    )
    .join(Organization, Organization.id == Workspace.organization_id)
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
        self.reload_failures = 0
        self.failing: set[Key] = set()
        """Deployments whose last reload failed (they keep serving the previous version)."""
        self._reload_locks: dict[Key, asyncio.Lock] = {}
        self._missing_versions: dict[tuple[str, str, str], float] = {}

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
            grouped.setdefault((qualified_name(row.org, row.slug), row.key, row.env), []).append(
                row
            )
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
                resolve = await resolver_for(s, row.workspace_id, row.graph)
            out.append((row.effective_from, build(ws, row.graph, row.resolved_schema, resolve)))
        return tuple(out)

    async def reload_one(self, ws: str, rs: str, env: str) -> None:
        # One reload per key at a time: each reads the database inside the lock, so the last
        # one to finish installs the latest state, never an older snapshot.
        lock = self._reload_locks.setdefault((ws, rs, env), asyncio.Lock())
        async with lock:
            org, slug = split_name(ws)
            q = _ALIAS_QUERY.where(
                Organization.slug == org,
                Workspace.slug == slug,
                Ruleset.key == rs,
                RulesetAlias.env == env,
            )
            async with self.sessions() as s:
                rows = (await s.execute(q)).all()
            try:
                schedule = await self._schedule(ws, list(rows)) if rows else None
            except Exception:
                self.failing.add((ws, rs, env))
                raise
            self.registry.put((ws, rs, env), schedule)
            self.failing.discard((ws, rs, env))
            self.reloads += 1

    async def load_version(self, ws: str, rs: str, semver: str) -> Deployment | None:
        cached = self.registry.get_version(ws, rs, semver)
        if cached is not None:
            return cached
        missing_until = self._missing_versions.get((ws, rs, semver))
        if missing_until is not None and missing_until > time.monotonic():
            return None  # asked again within seconds: no database query
        org, slug = split_name(ws)
        q = (
            select(RulesetVersion.graph, SchemaVersion.resolved_schema, Workspace.id)
            .join(Ruleset, Ruleset.id == RulesetVersion.ruleset_id)
            .join(Workspace, Workspace.id == Ruleset.workspace_id)
            .join(Organization, Organization.id == Workspace.organization_id)
            .outerjoin(SchemaVersion, SchemaVersion.id == RulesetVersion.schema_version_id)
            .where(
                Organization.slug == org,
                Workspace.slug == slug,
                Ruleset.key == rs,
                RulesetVersion.semver == semver,
                RulesetVersion.status != "archived",
            )
        )
        async with self.sessions() as s:
            row = (await s.execute(q)).first()
        if row is None:
            if len(self._missing_versions) >= KeyCache.MAX_ENTRIES:
                self._missing_versions.clear()
            self._missing_versions[(ws, rs, semver)] = time.monotonic() + 5
            return None
        async with self.sessions() as s:
            resolve = await resolver_for(s, row.id, row.graph)
        dep = build(ws, row.graph, row.resolved_schema, resolve)
        self.registry.put_version((ws, rs, semver), dep)
        return dep

    async def authenticate(self, key: str, key_hash: str) -> Principal | None:
        if not well_formed(key):
            return None  # no database query, no cache entry for random strings
        hit, principal = self.keys.get(key_hash)
        if hit:
            return principal
        q = (
            select(
                ApiClient.name,
                ApiClient.workspace_id,
                ApiClient.scopes,
                Workspace.slug,
                Workspace.organization_id,
                Organization.slug.label("org"),
            )
            .outerjoin(Workspace, Workspace.id == ApiClient.workspace_id)
            .outerjoin(Organization, Organization.id == Workspace.organization_id)
            .where(ApiClient.key_hash == key_hash, ApiClient.revoked_at.is_(None))
        )
        async with self.sessions() as s:
            row = (await s.execute(q)).first()
        if row is not None:
            principal = Principal(
                row.name,
                row.workspace_id,
                frozenset(row.scopes),
                qualified_name(row.org, row.slug) if row.slug else None,
                organization_id=row.organization_id,
            )
        self.keys.put(key_hash, principal)
        return principal

    # ------------------------------------------------------------------ notifications

    @property
    def listening(self) -> bool:
        """Whether NOTIFY messages arrive (otherwise only the periodic poll applies changes)."""
        return self._listener is not None and not self._listener.is_closed()

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
        elif event.get("kind") == "version":  # archived: no longer executable by number
            self.registry.drop_version((event["workspace"], event["ruleset"], event["semver"]))

    def _spawn(self, coro: Any) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.append(task)
        task.add_done_callback(self._forget)

    def _forget(self, task: asyncio.Task[None]) -> None:
        with contextlib.suppress(ValueError):
            self._tasks.remove(task)
        if not task.cancelled() and task.exception() is not None:
            self.reload_failures += 1
            log.error("reload failed", exc_info=task.exception())

    # ------------------------------------------------------------------ safety net

    async def check_drift(self) -> int:
        """Reload environments whose entries differ from the database; return how many."""
        async with self.sessions() as s:
            rows = (await s.execute(_HASH_QUERY)).all()
        wanted: dict[Key, list[tuple[dt.date, str]]] = {}
        for org, slug, rs, env, start, digest in rows:
            ws = qualified_name(org, slug)
            if ws == LOCAL_WORKSPACE:  # served from files; the slug is reserved
                continue
            wanted.setdefault((ws, rs, env), []).append((start, digest))
        current = {
            key: sorted((start, dep.hash) for start, dep in schedule)
            for key, schedule in self.registry.schedules().items()
            if key[0] != LOCAL_WORKSPACE
        }
        stale = [k for k, v in wanted.items() if current.get(k) != sorted(v)]
        gone = [k for k in current if k not in wanted]
        for key in gone:
            self.registry.put(key, None)
        fixed = len(gone)
        for ws, rs, env in stale:
            # One version that cannot be loaded must not keep the others stale.
            try:
                await self.reload_one(ws, rs, env)
                fixed += 1
            except Exception:
                self.reload_failures += 1
                log.exception("cannot reload %s/%s@%s", ws, rs, env)
        return fixed

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
