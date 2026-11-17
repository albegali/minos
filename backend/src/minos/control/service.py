"""Control-plane use cases: workspaces, entities, schemas, rule sets, drafts, publishing,
aliases, tests, API keys and audit. Every function works inside the caller's transaction.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from minos.db import (
    ALWAYS,
    NOTIFY_CHANNEL,
    ApiClient,
    AuditEvent,
    Entity,
    Ruleset,
    RulesetAlias,
    RulesetDraft,
    RulesetVersion,
    SchemaVersion,
    TestCase,
    Workspace,
)
from minos.engine import (
    CompiledRuleset,
    CompileError,
    ExecuteOptions,
    ExecutionLimitError,
    TypeCheckError,
    compile_ruleset,
)
from minos.engine.compiler import Resolver, dependencies
from minos.schema import (
    InputValidator,
    SchemaError,
    check_schema,
    find_refs,
    pin_refs,
    resolve_refs,
)

from .errors import Conflict, Invalid, NotFound, PreconditionFailed
from .keys import SCOPES, display_prefix, generate_key, hash_key, well_formed
from .testing import EXPECTATION_KEYS, compare

type Bump = Literal["major", "minor", "patch"]

SLUG = re.compile(r"^[a-z0-9][a-z0-9_.\-]{0,63}$")
ENV = re.compile(r"^[a-z][a-z0-9\-]{0,31}$")


def canonical_hash(doc: Any) -> str:
    raw = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


NAME_MAX: Final = 200
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _check_name(value: Any, what: str) -> None:
    """Names are stored in 200-character columns: refuse longer ones as a 422, not a 500."""
    if not isinstance(value, str) or not value.strip():
        raise Invalid(f"{what} is required")
    if len(value) > NAME_MAX:
        raise Invalid(f"{what} is longer than {NAME_MAX} characters")


def _check_slug(value: str, what: str) -> None:
    if not SLUG.match(value):
        raise Invalid(f"invalid {what} {value!r}: lowercase letters, digits, '.', '-', '_'")


async def audit(
    s: AsyncSession,
    actor: str,
    action: str,
    target: str,
    workspace_id: uuid.UUID | None,
    detail: dict[str, Any] | None = None,
) -> None:
    s.add(
        AuditEvent(
            actor=actor[:200],
            action=action,
            target=target[:300],
            workspace_id=workspace_id,
            detail=detail,
        )
    )


async def notify(s: AsyncSession, payload: dict[str, Any]) -> None:
    """Queue a NOTIFY; PostgreSQL delivers it only if the transaction commits."""
    await s.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": NOTIFY_CHANNEL, "payload": json.dumps(payload)},
    )


# --------------------------------------------------------------------------- workspaces


RESERVED_WORKSPACES: Final = frozenset({"local"})
"""``local`` is where the execution API serves rule sets read from files."""


async def create_workspace(s: AsyncSession, actor: str, slug: str, name: str) -> Workspace:
    _check_slug(slug, "workspace slug")
    if slug in RESERVED_WORKSPACES:
        raise Invalid(f"workspace slug {slug!r} is reserved")
    _check_name(name, "workspace name")
    ws = Workspace(slug=slug, name=name)
    s.add(ws)
    try:
        await s.flush()
    except IntegrityError as exc:
        raise Conflict(f"workspace {slug!r} already exists") from exc
    await audit(s, actor, "workspace.create", slug, ws.id)
    return ws


async def list_workspaces(s: AsyncSession) -> list[Workspace]:
    return list((await s.scalars(select(Workspace).order_by(Workspace.slug))).all())


async def get_workspace(s: AsyncSession, slug: str) -> Workspace:
    ws = await s.scalar(select(Workspace).where(Workspace.slug == slug))
    if ws is None:
        raise NotFound(f"workspace {slug!r} not found")
    return ws


# --------------------------------------------------------------------------- entities & schemas


async def create_entity(
    s: AsyncSession, actor: str, ws: Workspace, key: str, name: str, description: str | None
) -> Entity:
    _check_slug(key.lower(), "entity key")
    _check_name(name, "entity name")
    entity = Entity(workspace_id=ws.id, key=key, name=name, description=description)
    s.add(entity)
    try:
        await s.flush()
    except IntegrityError as exc:
        raise Conflict(f"entity {key!r} already exists") from exc
    await audit(s, actor, "entity.create", f"{ws.slug}/{key}", ws.id)
    return entity


async def list_entities(s: AsyncSession, ws: Workspace) -> list[Entity]:
    return list(
        await s.scalars(select(Entity).where(Entity.workspace_id == ws.id).order_by(Entity.key))
    )


async def get_entity(s: AsyncSession, ws: Workspace, key: str) -> Entity:
    entity = await s.scalar(select(Entity).where(Entity.workspace_id == ws.id, Entity.key == key))
    if entity is None:
        raise NotFound(f"entity {key!r} not found")
    return entity


async def add_schema_version(
    s: AsyncSession,
    actor: str,
    ws: Workspace,
    entity: Entity,
    json_schema: dict[str, Any],
    source: str,
) -> SchemaVersion:
    """Add a version, unless identical to the latest. ``{"$ref": "entity:<key>"}`` references
    are pinned to that entity's latest version and resolved (see :mod:`minos.schema.refs`)."""
    try:
        check_schema(json_schema)
        pinned, resolved = await _resolve_entity_refs(s, ws, entity, json_schema)
        check_schema(resolved)
    except SchemaError as exc:
        raise Invalid(f"invalid JSON Schema: {exc}") from exc
    await _lock(s, Entity, entity.id)  # serialise version numbering (latest + 1)
    latest = await latest_schema(s, entity)
    digest = canonical_hash(pinned)
    if latest is not None and latest.hash == digest:
        return latest  # unchanged: no new version
    sv = SchemaVersion(
        entity_id=entity.id,
        version=(latest.version + 1) if latest else 1,
        json_schema=pinned,
        resolved_schema=resolved,
        source=source,
        hash=digest,
        created_by=actor,
    )
    s.add(sv)
    await s.flush()
    await audit(s, actor, "schema.publish", f"{ws.slug}/{entity.key}@{sv.version}", ws.id)
    return sv


async def _resolve_entity_refs(
    s: AsyncSession, ws: Workspace, entity: Entity, json_schema: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """``(pinned, resolved)`` forms of an authored schema."""
    refs = find_refs(json_schema)
    if not refs:
        return json_schema, json_schema
    latest: dict[str, int] = {}
    targets: dict[tuple[str, int], dict[str, Any]] = {}
    for key, version in refs:
        try:
            other = await get_entity(s, ws, key)
        except NotFound:
            raise SchemaError(f"entity {key!r} referenced by the schema does not exist") from None
        if version is None:
            sv = await latest_schema(s, other)
            if sv is None:
                raise SchemaError(f"entity {key!r} has no schema yet")
            if other.id == entity.id:
                raise SchemaError(f"{key!r} cannot reference its own latest version")
            latest[key] = sv.version
        else:
            try:
                sv = await get_schema_version(s, other, version)
            except NotFound as exc:
                raise SchemaError(exc.detail) from None
        targets[(key, sv.version)] = sv.resolved_schema
    pinned = pin_refs(json_schema, latest)
    return pinned, resolve_refs(pinned, targets)


async def schema_references(
    s: AsyncSession, ws: Workspace, sv: SchemaVersion
) -> list[dict[str, Any]]:
    """Entities a version references: ``{entity, version, latest}`` (``latest`` > ``version``
    means the reference can be moved forward with a new version)."""
    out = []
    for key, version in find_refs(sv.json_schema):
        try:
            newest = await latest_schema(s, await get_entity(s, ws, key))
        except NotFound:
            newest = None
        latest = newest.version if newest else None
        out.append({"entity": key, "version": version, "latest": latest})
    return out


async def entities_referencing(s: AsyncSession, ws: Workspace, entity: Entity) -> list[str]:
    """Entities whose latest schema version references ``entity`` (any version)."""
    out = []
    for other in await list_entities(s, ws):
        if other.id == entity.id:
            continue
        sv = await latest_schema(s, other)
        if sv is not None and any(k == entity.key for k, _ in find_refs(sv.json_schema)):
            out.append(other.key)
    return out


async def latest_schema(s: AsyncSession, entity: Entity) -> SchemaVersion | None:
    return await s.scalar(
        select(SchemaVersion)
        .where(SchemaVersion.entity_id == entity.id)
        .order_by(SchemaVersion.version.desc())
        .limit(1)
    )


async def get_schema_version(s: AsyncSession, entity: Entity, version: int) -> SchemaVersion:
    sv = await s.scalar(
        select(SchemaVersion).where(
            SchemaVersion.entity_id == entity.id, SchemaVersion.version == version
        )
    )
    if sv is None:
        raise NotFound(f"schema version {version} of {entity.key!r} not found")
    return sv


async def list_schema_versions(s: AsyncSession, entity: Entity) -> list[SchemaVersion]:
    return list(
        await s.scalars(
            select(SchemaVersion)
            .where(SchemaVersion.entity_id == entity.id)
            .order_by(SchemaVersion.version.desc())
        )
    )


# --------------------------------------------------------------------------- rule sets & drafts


def starter_graph(key: str) -> dict[str, Any]:
    return {
        "rgdVersion": "1.0",
        "ruleset": key,
        "settings": {"mode": "fail_fast", "locale": "it"},
        "nodes": [
            {"id": "start", "type": "start"},
            {"id": "end", "type": "end", "outcome": "valid"},
        ],
        "edges": [{"from": "start", "to": "end"}],
    }


async def create_ruleset(
    s: AsyncSession,
    actor: str,
    ws: Workspace,
    entity: Entity,
    key: str,
    name: str,
    description: str | None,
    graph: dict[str, Any] | None = None,
) -> Ruleset:
    _check_slug(key, "ruleset key")
    _check_name(name, "rule set name")
    rs = Ruleset(
        workspace_id=ws.id, entity_id=entity.id, key=key, name=name, description=description
    )
    s.add(rs)
    try:
        await s.flush()
    except IntegrityError as exc:
        raise Conflict(f"ruleset {key!r} already exists") from exc
    schema = await latest_schema(s, entity)
    s.add(
        RulesetDraft(
            ruleset_id=rs.id,
            schema_version_id=schema.id if schema else None,
            graph=_normalise_graph(graph or starter_graph(key), key),
            updated_by=actor,
        )
    )
    await s.flush()
    await audit(s, actor, "ruleset.create", f"{ws.slug}/{key}", ws.id)
    return rs


async def list_rulesets(s: AsyncSession, ws: Workspace) -> list[Ruleset]:
    return list(
        await s.scalars(select(Ruleset).where(Ruleset.workspace_id == ws.id).order_by(Ruleset.key))
    )


async def _lock(s: AsyncSession, model: type[Entity] | type[Ruleset], row_id: uuid.UUID) -> None:
    """Row lock that serialises writers of ``row_id``'s children (version numbers, aliases).

    ``FOR NO KEY UPDATE``: unlike ``FOR UPDATE`` it does not block inserts of rows that only
    reference it (tests, aliases), which take a ``KEY SHARE`` lock.
    """
    await s.execute(select(model.id).where(model.id == row_id).with_for_update(key_share=True))


async def get_ruleset(
    s: AsyncSession, ws: Workspace, key: str, *, for_update: bool = False
) -> Ruleset:
    q = select(Ruleset).where(Ruleset.workspace_id == ws.id, Ruleset.key == key)
    if for_update:
        q = q.with_for_update(key_share=True)
    rs = await s.scalar(q)
    if rs is None:
        raise NotFound(f"ruleset {key!r} not found")
    return rs


def _normalise_graph(graph: Any, key: str) -> dict[str, Any]:
    if not isinstance(graph, dict):
        raise Invalid("graph must be a JSON object")
    out = dict(graph)
    out["ruleset"] = key
    out.pop("version", None)  # assigned at publish time
    return out


async def get_draft(s: AsyncSession, rs: Ruleset) -> RulesetDraft:
    draft = await s.get(RulesetDraft, rs.id)
    assert draft is not None, "every ruleset has a draft"
    return draft


async def save_draft(
    s: AsyncSession,
    actor: str,
    ws: Workspace,
    rs: Ruleset,
    graph: dict[str, Any],
    if_match: int | None,
    schema_version: int | None = None,
) -> RulesetDraft:
    draft = await s.get(RulesetDraft, rs.id, with_for_update=True)
    assert draft is not None
    if if_match is not None and if_match != draft.lock_version:
        raise PreconditionFailed(
            f"draft changed since version {if_match} (now {draft.lock_version})",
            {"lockVersion": draft.lock_version},
        )
    draft.graph = _normalise_graph(graph, rs.key)
    if schema_version is not None:
        entity = await s.get(Entity, rs.entity_id)
        assert entity is not None
        draft.schema_version_id = (await get_schema_version(s, entity, schema_version)).id
    draft.lock_version += 1
    draft.updated_by = actor
    await s.flush()
    await audit(s, actor, "draft.save", f"{ws.slug}/{rs.key}", ws.id, {"lock": draft.lock_version})
    return draft


async def _draft_schema(s: AsyncSession, draft: RulesetDraft) -> SchemaVersion | None:
    if draft.schema_version_id is None:
        return None
    return await s.get(SchemaVersion, draft.schema_version_id)


@dataclass(frozen=True, slots=True)
class Validation:
    valid: bool
    issues: list[dict[str, str]]
    warnings: list[str]
    compiled: CompiledRuleset | None


def compile_checked(
    graph: dict[str, Any], schema: dict[str, Any] | None, resolve: Resolver | None = None
) -> Validation:
    try:
        compiled = compile_ruleset(graph, schema, resolve)
    except TypeCheckError as exc:
        return Validation(False, [i.as_dict() for i in exc.issues], [], None)
    except CompileError as exc:
        return Validation(False, [{"where": exc.where or "", "message": exc.message}], [], None)
    return Validation(True, [], list(compiled.warnings), compiled)


async def resolver_for(s: AsyncSession, workspace: str, graph: dict[str, Any]) -> Resolver:
    """Load (recursively) the published versions a graph's sub-ruleset nodes pin, and return
    a resolver that compiles them on demand, once each."""
    sources: dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any] | None]] = {}

    async def load(doc: dict[str, Any]) -> None:
        for key, version in dependencies(doc):
            if (key, version) in sources:
                continue
            row = (
                await s.execute(
                    select(RulesetVersion.graph, SchemaVersion.resolved_schema)
                    .join(Ruleset, Ruleset.id == RulesetVersion.ruleset_id)
                    .join(Workspace, Workspace.id == Ruleset.workspace_id)
                    .outerjoin(SchemaVersion, SchemaVersion.id == RulesetVersion.schema_version_id)
                    .where(
                        Workspace.slug == workspace,
                        Ruleset.key == key,
                        RulesetVersion.semver == version,
                    )
                )
            ).first()
            if row is not None:
                sources[(key, version)] = (row.graph, row.resolved_schema)
                await load(row.graph)

    await load(graph)
    return resolver_from(sources)


def resolver_from(
    sources: Mapping[tuple[str, str], tuple[dict[str, Any], dict[str, Any] | None]],
) -> Resolver:
    """Resolver over already loaded ``(key, version) -> (graph, schema)`` documents."""
    compiled: dict[tuple[str, str], CompiledRuleset] = {}
    resolving: set[tuple[str, str]] = set()

    def resolve(key: str, version: str) -> CompiledRuleset:
        ident = (key, version)
        if ident in compiled:
            return compiled[ident]
        if ident not in sources:
            raise CompileError(f"version {version} of {key!r} is not published in this workspace")
        if ident in resolving:
            raise CompileError(f"{key}@{version} includes itself")
        resolving.add(ident)
        try:
            graph, schema = sources[ident]
            compiled[ident] = compile_ruleset(graph, schema, resolve)
        finally:
            resolving.discard(ident)
        return compiled[ident]

    return resolve


async def validate_draft(s: AsyncSession, rs: Ruleset) -> Validation:
    draft = await get_draft(s, rs)
    sv = await _draft_schema(s, draft)
    ws = await s.get(Workspace, rs.workspace_id)
    assert ws is not None
    resolve = await resolver_for(s, ws.slug, draft.graph)
    # Compiling and running rules is CPU-bound: worker threads keep the event loop, which also
    # serves executions, responsive.
    return await asyncio.to_thread(
        compile_checked, draft.graph, sv.resolved_schema if sv else None, resolve
    )


async def simulate_draft(
    s: AsyncSession, rs: Ruleset, data: Any, options: ExecuteOptions
) -> dict[str, Any]:
    validation = await validate_draft(s, rs)
    if validation.compiled is None:
        raise Invalid("the draft does not compile", {"issues": validation.issues})
    try:
        return validation.compiled.execute(data, options)
    except ExecutionLimitError as exc:
        raise Invalid(str(exc)) from exc


# --------------------------------------------------------------------------- tests


async def add_test(
    s: AsyncSession,
    actor: str,
    ws: Workspace,
    rs: Ruleset,
    name: str,
    data: Any,
    expected: dict[str, Any],
    reference_date: str | None,
) -> TestCase:
    _check_name(name, "test name")
    if reference_date is not None and not (
        isinstance(reference_date, str) and _ISO_DATE.match(reference_date)
    ):
        raise Invalid("referenceDate must be an ISO date (YYYY-MM-DD)")
    if not isinstance(expected, dict):
        raise Invalid("expected must be an object")
    unknown = set(expected) - EXPECTATION_KEYS
    if unknown or not expected:
        raise Invalid(f"expected must use some of {sorted(EXPECTATION_KEYS)}")
    tc = TestCase(
        ruleset_id=rs.id, name=name, input=data, expected=expected, reference_date=reference_date
    )
    s.add(tc)
    try:
        await s.flush()
    except IntegrityError as exc:
        raise Conflict(f"test {name!r} already exists") from exc
    await audit(s, actor, "test.create", f"{ws.slug}/{rs.key}/{name}", ws.id)
    return tc


async def list_tests(s: AsyncSession, rs: Ruleset) -> list[TestCase]:
    return list(
        await s.scalars(
            select(TestCase).where(TestCase.ruleset_id == rs.id).order_by(TestCase.name)
        )
    )


async def replace_test(
    s: AsyncSession,
    actor: str,
    ws: Workspace,
    rs: Ruleset,
    name: str,
    data: Any,
    expected: dict[str, Any],
    reference_date: str | None,
) -> tuple[TestCase, bool]:
    """Create or replace the test ``name``; returns ``(test, created)``."""
    old = await s.scalar(
        select(TestCase).where(TestCase.ruleset_id == rs.id, TestCase.name == name)
    )
    if old is not None:
        await s.delete(old)
        await s.flush()  # the unit of work would otherwise insert before deleting
    tc = await add_test(s, actor, ws, rs, name, data, expected, reference_date)
    if old is not None:
        await audit(s, actor, "test.replace", f"{ws.slug}/{rs.key}/{name}", ws.id)
    return tc, old is None


async def delete_test(s: AsyncSession, actor: str, ws: Workspace, rs: Ruleset, name: str) -> None:
    tc = await s.scalar(select(TestCase).where(TestCase.ruleset_id == rs.id, TestCase.name == name))
    if tc is None:
        raise NotFound(f"test {name!r} not found")
    await s.delete(tc)
    await audit(s, actor, "test.delete", f"{ws.slug}/{rs.key}/{name}", ws.id)


def run_tests(
    compiled: CompiledRuleset, tests: list[TestCase], schema: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Run ``tests``; with ``schema``, inputs are first checked against it, as the execution
    API does, so that a test cannot pass on an input production would refuse."""
    validator = InputValidator(schema) if schema else None
    out = []
    for tc in tests:
        opts = ExecuteOptions(reference_date=tc.reference_date, request_id=f"test:{tc.name}")
        if validator is not None and not validator.is_valid(tc.input):
            errors = validator.errors(tc.input, limit=5)
            diffs = [
                f"input does not match the entity schema: {e['path'] or '/'} {e['message']}"
                for e in errors
            ]
            out.append({"name": tc.name, "passed": False, "differences": diffs})
            continue
        try:
            result = compiled.execute(tc.input, opts)
            diffs = compare(tc.expected, result)
        except ExecutionLimitError as exc:
            diffs = [str(exc)]
        out.append({"name": tc.name, "passed": not diffs, "differences": diffs})
    return out


async def run_draft_tests(s: AsyncSession, rs: Ruleset) -> dict[str, Any]:
    validation = await validate_draft(s, rs)
    if validation.compiled is None:
        raise Invalid("the draft does not compile", {"issues": validation.issues})
    sv = await _draft_schema(s, await get_draft(s, rs))
    cases = await list_tests(s, rs)
    schema = sv.resolved_schema if sv else None
    results = await asyncio.to_thread(run_tests, validation.compiled, cases, schema)
    return {"passed": all(r["passed"] for r in results), "tests": results}


# --------------------------------------------------------------------------- publish & aliases


def _content_hash(graph: dict[str, Any]) -> str:
    """Hash of a graph's content, without the version stamp publishing adds."""
    return canonical_hash({k: v for k, v in graph.items() if k != "version"})


def _bump(current: tuple[int, int, int] | None, bump: Bump) -> tuple[int, int, int]:
    if current is None:
        return {"major": (1, 0, 0), "minor": (0, 1, 0), "patch": (0, 0, 1)}[bump]
    ma, mi, pa = current
    if bump == "major":
        return ma + 1, 0, 0
    if bump == "minor":
        return ma, mi + 1, 0
    return ma, mi, pa + 1


async def latest_version(s: AsyncSession, rs: Ruleset) -> RulesetVersion | None:
    return await s.scalar(
        select(RulesetVersion)
        .where(RulesetVersion.ruleset_id == rs.id)
        .order_by(
            RulesetVersion.major.desc(), RulesetVersion.minor.desc(), RulesetVersion.patch.desc()
        )
        .limit(1)
    )


async def publish(
    s: AsyncSession,
    actor: str,
    ws: Workspace,
    rs: Ruleset,
    bump: Bump,
    notes: str | None,
    promote_to: str | None = None,
    *,
    require_tests: bool = False,
) -> tuple[RulesetVersion, list[dict[str, Any]], bool]:
    """Compile, test and freeze the draft as a new immutable version.

    Returns ``(version, test results, created)``. A draft identical to the latest version
    (same graph and schema) publishes nothing: that version is returned with ``created``
    false (and still promoted when asked), so that a retried publish is harmless.
    """
    rs = await get_ruleset(s, ws, rs.key, for_update=True)  # serialise concurrent publishes
    draft = await get_draft(s, rs)
    sv = await _draft_schema(s, draft)
    latest = await latest_version(s, rs)
    if (
        latest is not None
        and latest.schema_version_id == (sv.id if sv else None)
        and _content_hash(latest.graph) == _content_hash(draft.graph)
    ):
        if promote_to:
            await set_alias(s, actor, ws, rs, promote_to, latest.semver)
        return latest, [], False
    numbers = _bump((latest.major, latest.minor, latest.patch) if latest else None, bump)
    semver = "{}.{}.{}".format(*numbers)

    graph = dict(draft.graph, version=semver)
    resolve = await resolver_for(s, ws.slug, graph)
    cases = await list_tests(s, rs)
    validation = await asyncio.to_thread(
        compile_checked, graph, sv.resolved_schema if sv else None, resolve
    )
    if validation.compiled is None:
        raise Invalid("the draft does not compile", {"issues": validation.issues})
    if require_tests and not cases:
        raise Invalid("publishing needs at least one test (MINOS_PUBLISH_REQUIRES_TESTS)")
    tests = await asyncio.to_thread(
        run_tests, validation.compiled, cases, sv.resolved_schema if sv else None
    )
    failed = [t for t in tests if not t["passed"]]
    if failed:
        raise Invalid(f"{len(failed)} test(s) failed", {"tests": tests})

    version = RulesetVersion(
        ruleset_id=rs.id,
        semver=semver,
        major=numbers[0],
        minor=numbers[1],
        patch=numbers[2],
        schema_version_id=sv.id if sv else None,
        graph=graph,
        hash=validation.compiled.hash,
        notes=notes,
        published_by=actor,
    )
    s.add(version)
    await s.flush()
    await audit(
        s,
        actor,
        "ruleset.publish",
        f"{ws.slug}/{rs.key}@{semver}",
        ws.id,
        {"hash": version.hash, "tests": len(tests)},
    )
    if promote_to:
        await set_alias(s, actor, ws, rs, promote_to, semver)
    return version, tests, True


async def archive_version(
    s: AsyncSession, actor: str, ws: Workspace, rs: Ruleset, semver: str
) -> RulesetVersion:
    """Withdraw a published version: it can no longer be promoted nor executed by number.
    Refused while an environment still points at it (move the environment first)."""
    await _lock(s, Ruleset, rs.id)
    version = await get_version(s, rs, semver)
    envs = list(
        await s.scalars(
            select(RulesetAlias.env).where(
                RulesetAlias.ruleset_id == rs.id, RulesetAlias.version_id == version.id
            )
        )
    )
    if envs:
        raise Conflict(
            f"version {semver} is in use by {', '.join(sorted(set(envs)))}: "
            "point those environments at another version first"
        )
    if version.status != "archived":
        version.status = "archived"
        await audit(s, actor, "version.archive", f"{ws.slug}/{rs.key}@{semver}", ws.id)
        await notify(
            s, {"kind": "version", "workspace": ws.slug, "ruleset": rs.key, "semver": semver}
        )
    return version


async def list_versions(s: AsyncSession, rs: Ruleset) -> list[RulesetVersion]:
    return list(
        await s.scalars(
            select(RulesetVersion)
            .where(RulesetVersion.ruleset_id == rs.id)
            .order_by(
                RulesetVersion.major.desc(),
                RulesetVersion.minor.desc(),
                RulesetVersion.patch.desc(),
            )
        )
    )


async def get_version(s: AsyncSession, rs: Ruleset, semver: str) -> RulesetVersion:
    v = await s.scalar(
        select(RulesetVersion).where(
            RulesetVersion.ruleset_id == rs.id, RulesetVersion.semver == semver
        )
    )
    if v is None:
        raise NotFound(f"version {semver!r} of {rs.key!r} not found")
    return v


async def set_alias(
    s: AsyncSession,
    actor: str,
    ws: Workspace,
    rs: Ruleset,
    env: str,
    semver: str,
    effective_from: dt.date | None = None,
) -> RulesetAlias:
    """Point ``env`` at ``semver`` from ``effective_from`` (``None``: with no start date)."""
    if not ENV.match(env):
        raise Invalid(f"invalid environment name {env!r}")
    start = effective_from or ALWAYS
    version = await get_version(s, rs, semver)
    if version.status == "archived":
        raise Conflict(f"version {semver} is archived")
    # Lock the rule set, not the entry: a missing entry cannot be locked, and two first-time
    # writers would both insert it.
    await _lock(s, Ruleset, rs.id)
    alias = await s.get(RulesetAlias, (rs.id, env, start))
    previous = None
    if alias is None:
        alias = RulesetAlias(
            ruleset_id=rs.id, env=env, effective_from=start, version_id=version.id, updated_by=actor
        )
        s.add(alias)
    else:
        previous = alias.version_id
        alias.version_id = version.id
        alias.updated_by = actor
    await s.flush()
    await audit(
        s,
        actor,
        "alias.set",
        f"{ws.slug}/{rs.key}@{env}",
        ws.id,
        {
            "version": semver,
            "effectiveFrom": effective_from.isoformat() if effective_from else None,
            "previousVersionId": str(previous) if previous else None,
        },
    )
    await notify(s, {"kind": "alias", "workspace": ws.slug, "ruleset": rs.key, "env": env})
    return alias


@dataclass(frozen=True, slots=True)
class AliasEntry:
    env: str
    version: str
    effective_from: dt.date | None


async def list_aliases(s: AsyncSession, rs: Ruleset) -> list[AliasEntry]:
    rows = await s.execute(
        select(RulesetAlias.env, RulesetVersion.semver, RulesetAlias.effective_from)
        .join(RulesetVersion, RulesetVersion.id == RulesetAlias.version_id)
        .where(RulesetAlias.ruleset_id == rs.id)
        .order_by(RulesetAlias.env, RulesetAlias.effective_from)
    )
    return [
        AliasEntry(env, semver, None if start == ALWAYS else start)
        for env, semver, start in rows.all()
    ]


def current_aliases(entries: list[AliasEntry], on: dt.date) -> dict[str, str]:
    """Version each environment runs on day ``on``."""
    out: dict[str, str] = {}
    for e in entries:  # ordered by env, then start date
        if e.effective_from is None or e.effective_from <= on:
            out[e.env] = e.version
    return out


async def delete_alias(
    s: AsyncSession,
    actor: str,
    ws: Workspace,
    rs: Ruleset,
    env: str,
    effective_from: dt.date | None = None,
    *,
    all_entries: bool = True,
) -> None:
    """Remove one scheduled entry (``effective_from``) or, by default, the whole environment."""
    q = select(RulesetAlias).where(RulesetAlias.ruleset_id == rs.id, RulesetAlias.env == env)
    if not all_entries:
        q = q.where(RulesetAlias.effective_from == (effective_from or ALWAYS))
    entries = list(await s.scalars(q))
    if not entries:
        raise NotFound(f"alias {env!r} not found")
    for entry in entries:
        await s.delete(entry)
    await audit(
        s,
        actor,
        "alias.delete",
        f"{ws.slug}/{rs.key}@{env}",
        ws.id,
        {"effectiveFrom": None if all_entries else str(effective_from or "")},
    )
    await notify(s, {"kind": "alias", "workspace": ws.slug, "ruleset": rs.key, "env": env})


# --------------------------------------------------------------------------- API keys


async def create_api_client(
    s: AsyncSession,
    actor: str,
    ws: Workspace | None,
    name: str,
    scopes: list[str],
) -> tuple[ApiClient, str]:
    """Create a key; the clear-text key is returned once and never stored."""
    _check_name(name, "key name")
    bad = set(scopes) - SCOPES
    if not scopes or bad:
        raise Invalid(f"scopes must be a non-empty subset of {sorted(SCOPES)}")
    if "admin" in scopes and ws is not None:
        raise Invalid("the admin scope is global: create it without a workspace")
    if "admin" not in scopes and ws is None:
        raise Invalid("non-admin keys belong to a workspace")
    key = generate_key()
    client = ApiClient(
        workspace_id=ws.id if ws else None,
        name=name,
        key_prefix=display_prefix(key),
        key_hash=hash_key(key),
        scopes=sorted(set(scopes)),
    )
    s.add(client)
    await s.flush()
    await audit(
        s,
        actor,
        "apikey.create",
        client.key_prefix,
        ws.id if ws else None,
        {"name": name, "scopes": client.scopes},
    )
    return client, key


async def list_api_clients(s: AsyncSession, ws: Workspace | None) -> list[ApiClient]:
    """Keys of ``ws``, or the global (admin) keys when ``ws`` is ``None``."""
    owner = ApiClient.workspace_id == ws.id if ws else ApiClient.workspace_id.is_(None)
    return list(await s.scalars(select(ApiClient).where(owner).order_by(ApiClient.created_at)))


async def revoke_api_client(
    s: AsyncSession, actor: str, ws: Workspace | None, client_id: uuid.UUID
) -> None:
    """Revoke a key of ``ws``, or a global (admin) key when ``ws`` is ``None``."""
    client = await s.get(ApiClient, client_id)
    if client is None or client.workspace_id != (ws.id if ws else None):
        raise NotFound("API key not found")
    if client.revoked_at is None:
        client.revoked_at = await s.scalar(select(func.now()))
        await audit(s, actor, "apikey.revoke", client.key_prefix, ws.id if ws else None)
        await notify(s, {"kind": "apikey", "keyHash": client.key_hash})


async def find_api_client(s: AsyncSession, key: str) -> ApiClient | None:
    if not well_formed(key):
        return None
    client = await s.scalar(select(ApiClient).where(ApiClient.key_hash == hash_key(key)))
    if client is None or client.revoked_at is not None:
        return None
    return client


async def list_audit(s: AsyncSession, ws: Workspace, limit: int = 100) -> list[AuditEvent]:
    return list(
        await s.scalars(
            select(AuditEvent)
            .where(AuditEvent.workspace_id == ws.id)
            .order_by(AuditEvent.id.desc())
            .limit(limit)
        )
    )
