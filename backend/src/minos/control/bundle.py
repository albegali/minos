"""Bundles: a rule set with its entity schema and tests in one JSON file.

Used to move rule sets between installations, keep them in Git, or share them. Pinned
sub-rulesets are listed under ``dependencies`` but not included: import them first. The schema
is the resolved one: entities it references travel embedded under ``$defs``, so the bundle
imports into a workspace that does not have them.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from minos import __version__
from minos.db import Entity, Ruleset, SchemaVersion, Workspace
from minos.engine.compiler import dependencies

from . import service as svc
from .errors import Invalid, NotFound

FORMAT: Final = "minos-bundle/1"


async def export_bundle(
    s: AsyncSession, ws: Workspace, rs: Ruleset, version: str | None
) -> dict[str, Any]:
    """Bundle the draft (``version=None``) or a published version."""
    entity = await s.get(Entity, rs.entity_id)
    assert entity is not None
    if version is None:
        draft = await svc.get_draft(s, rs)
        graph, schema_id, source = draft.graph, draft.schema_version_id, "draft"
    else:
        v = await svc.get_version(s, rs, version)
        graph, schema_id, source = v.graph, v.schema_version_id, v.semver
    schema = await s.get(SchemaVersion, schema_id) if schema_id else None
    tests = await svc.list_tests(s, rs)
    return {
        "format": FORMAT,
        "exportedAt": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "minosVersion": __version__,
        "source": {"workspace": ws.slug, "ruleset": rs.key, "version": source},
        "ruleset": {"key": rs.key, "name": rs.name, "description": rs.description},
        "entity": {"key": entity.key, "name": entity.name, "description": entity.description},
        "schema": schema.resolved_schema if schema else None,
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


def _require(bundle: Any, key: str, kind: type) -> Any:
    value = bundle.get(key) if isinstance(bundle, dict) else None
    if not isinstance(value, kind):
        raise Invalid(f"bundle: '{key}' is missing or not a {kind.__name__}")
    return value


async def import_bundle(s: AsyncSession, actor: str, ws: Workspace, bundle: Any) -> dict[str, Any]:
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

    try:
        entity = await svc.get_entity(s, ws, entity_key)
        entity_created = False
    except NotFound:
        entity = await svc.create_entity(
            s,
            actor,
            ws,
            entity_key,
            entity_meta.get("name") or entity_key,
            entity_meta.get("description"),
        )
        entity_created = True

    schema_version = None
    if isinstance(bundle.get("schema"), dict):
        sv = await svc.add_schema_version(s, actor, ws, entity, bundle["schema"], "import")
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
    await svc.audit(s, actor, "ruleset.import", f"{ws.slug}/{key}", ws.id, {"tests": len(tests)})
    return {
        "ruleset": key,
        "created": created,
        "entity": entity_key,
        "entityCreated": entity_created,
        "schemaVersion": schema_version,
        "tests": len(tests),
        "dependencies": bundle.get("dependencies") or [],
    }
