"""Bundles: a rule set with its entity schema and tests in one JSON file.

Used to move rule sets between installations, keep them in Git, or share them. Pinned
sub-rulesets are listed under ``dependencies`` but not included: import them first.

The schema travels twice: ``schema`` is the resolved, standalone form (readable on its own),
``authoredSchema`` the form as written, with ``entity:K@v`` references. Every entity it
references, directly or not, is listed in ``entities`` (referenced ones first) with its authored
schema. On import each of them is matched to an identical version of the target workspace, or
added as a new version there, and the references are renumbered accordingly: the imported
entity keeps its links to the others. Bundles without ``entities`` (older ones) import the
resolved schema.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from minos import __version__
from minos.db import Entity, Ruleset, SchemaVersion, Workspace
from minos.engine.compiler import dependencies
from minos.schema import SchemaError, find_refs, repin_refs

from . import service as svc
from .errors import Invalid, NotFound
from .identity import Actor

FORMAT: Final = "minos-bundle/1"


async def export_bundle(
    s: AsyncSession, ws: Workspace, rs: Ruleset, version: str | None
) -> dict[str, Any]:
    """Bundle the draft (``version=None``) or a published version."""
    entity = await s.get(Entity, rs.entity_id)
    if entity is None:  # pragma: no cover - foreign key
        raise NotFound("entity of the rule set not found")
    if version is None:
        draft = await svc.get_draft(s, rs)
        graph, schema_id, source = draft.graph, draft.schema_version_id, "draft"
    else:
        v = await svc.get_version(s, rs, version)
        graph, schema_id, source = v.graph, v.schema_version_id, v.semver
    schema = await s.get(SchemaVersion, schema_id) if schema_id else None
    tests = await svc.list_tests(s, rs)
    referenced = await _referenced_entities(s, ws, schema.json_schema) if schema else []
    return {
        "format": FORMAT,
        "exportedAt": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "minosVersion": __version__,
        "source": {"workspace": ws.slug, "ruleset": rs.key, "version": source},
        "ruleset": {"key": rs.key, "name": rs.name, "description": rs.description},
        "entity": {"key": entity.key, "name": entity.name, "description": entity.description},
        "schema": schema.resolved_schema if schema else None,
        "authoredSchema": schema.json_schema if schema else None,
        "entities": referenced,
        "graph": graph,
        "tests": [
            {
                "name": t.name,
                "input": t.input,
                "expected": t.expected,
                "referenceDate": t.reference_date,
            }
            for t in tests
        ],
        "dependencies": [{"ruleset": k, "version": v} for k, v in dependencies(graph)],
    }


async def _referenced_entities(
    s: AsyncSession, ws: Workspace, schema: dict[str, Any]
) -> list[dict[str, Any]]:
    """The entity versions ``schema`` references, directly or not, referenced ones first."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()

    async def visit(doc: dict[str, Any]) -> None:
        for key, version in find_refs(doc):
            if version is None or (key, version) in seen:
                continue
            seen.add((key, version))
            entity = await svc.get_entity(s, ws, key)
            sv = await svc.get_schema_version(s, entity, version)
            await visit(sv.json_schema)
            out.append(
                {
                    "key": key,
                    "name": entity.name,
                    "description": entity.description,
                    "version": version,
                    "schema": sv.json_schema,
                }
            )

    await visit(schema)
    return out


async def _get_or_create_entity(
    s: AsyncSession, actor: Actor, ws: Workspace, meta: dict[str, Any], key: str
) -> tuple[Entity, bool]:
    try:
        return await svc.get_entity(s, ws, key), False
    except NotFound:
        entity = await svc.create_entity(
            s, actor, ws, key, meta.get("name") or key, meta.get("description")
        )
        return entity, True


async def _import_entities(
    s: AsyncSession, actor: Actor, ws: Workspace, entities: list[Any]
) -> dict[tuple[str, int], int]:
    """Bring the referenced entity versions of a bundle into ``ws``: reuse an identical
    version, or add one. Returns ``(key, version in the bundle) -> version in ws``."""
    versions: dict[tuple[str, int], int] = {}
    for item in entities:
        if not isinstance(item, dict):
            raise Invalid("bundle: every item of 'entities' must be an object")
        key, version, schema = item.get("key"), item.get("version"), item.get("schema")
        if not isinstance(key, str) or not isinstance(version, int) or not isinstance(schema, dict):
            raise Invalid("bundle: every entity needs 'key', 'version' and 'schema'")
        try:
            authored = repin_refs(schema, versions)
        except SchemaError as exc:
            raise Invalid(f"bundle: entity {key!r}: {exc}") from exc
        entity, _ = await _get_or_create_entity(s, actor, ws, item, key)
        same = await s.scalar(
            select(SchemaVersion.version).where(
                SchemaVersion.entity_id == entity.id,
                SchemaVersion.hash == svc.canonical_hash(authored),
            )
        )
        if same is None:
            sv = await svc.add_schema_version(s, actor, ws, entity, authored, "import")
            same = sv.version
        versions[(key, version)] = same
    return versions


def _require(bundle: Any, key: str, kind: type) -> Any:
    value = bundle.get(key) if isinstance(bundle, dict) else None
    if not isinstance(value, kind):
        raise Invalid(f"bundle: '{key}' is missing or not a {kind.__name__}")
    return value


async def import_bundle(
    s: AsyncSession, actor: Actor, ws: Workspace, bundle: Any
) -> dict[str, Any]:
    """Create or update the entity, schema, rule set draft and tests of a bundle.

    The rule set lands as a draft (never published automatically); tests with the same name
    are replaced.
    """
    if not isinstance(bundle, dict) or bundle.get("format") != FORMAT:
        raise Invalid(f"not a Minos bundle (expected format {FORMAT!r})")
    rs_meta = _require(bundle, "ruleset", dict)
    entity_meta = _require(bundle, "entity", dict)
    graph = _require(bundle, "graph", dict)
    tests = bundle.get("tests") or []
    if not isinstance(tests, list):
        raise Invalid("bundle: 'tests' must be a list")
    key, entity_key = rs_meta.get("key"), entity_meta.get("key")
    if not isinstance(key, str) or not isinstance(entity_key, str):
        raise Invalid("bundle: ruleset.key and entity.key are required")

    referenced = bundle.get("entities")
    authored = bundle.get("authoredSchema")
    if referenced is not None and not isinstance(referenced, list):
        raise Invalid("bundle: 'entities' must be a list")
    # Referenced entities first: the schema below points at their versions in this workspace.
    versions = await _import_entities(s, actor, ws, referenced or [])
    entity, entity_created = await _get_or_create_entity(s, actor, ws, entity_meta, entity_key)

    schema_version = None
    schema: Any
    if isinstance(authored, dict) and referenced is not None:
        try:
            schema = repin_refs(authored, versions)
        except SchemaError as exc:
            raise Invalid(f"bundle: {exc}") from exc
    else:
        schema = bundle.get("schema")
    if isinstance(schema, dict):
        sv = await svc.add_schema_version(s, actor, ws, entity, schema, "import")
        schema_version = sv.version

    try:
        rs = await svc.get_ruleset(s, ws, key)
        if rs.entity_id != entity.id:
            raise Invalid(f"rule set {key!r} exists for another entity")
        created = False
    except NotFound:
        rs = await svc.create_ruleset(
            s, actor, ws, entity, key, rs_meta.get("name") or key, rs_meta.get("description")
        )
        created = True
    await svc.save_draft(s, actor, ws, rs, graph, None, schema_version)

    existing = {t.name for t in await svc.list_tests(s, rs)}
    for t in tests:
        if not isinstance(t, dict) or not isinstance(t.get("name"), str):
            raise Invalid("bundle: every test needs a name")
        if t["name"] in existing:
            await svc.delete_test(s, actor, ws, rs, t["name"])
            await s.flush()  # the unit of work would otherwise insert before deleting
        await svc.add_test(
            s,
            actor,
            ws,
            rs,
            t["name"],
            t.get("input"),
            t.get("expected") or {},
            t.get("referenceDate"),
        )
    await svc.audit(s, actor, "ruleset.import", f"{ws.slug}/{key}", ws, {"tests": len(tests)})
    return {
        "ruleset": key,
        "created": created,
        "entity": entity_key,
        "entityCreated": entity_created,
        "schemaVersion": schema_version,
        "tests": len(tests),
        "dependencies": bundle.get("dependencies") or [],
    }
