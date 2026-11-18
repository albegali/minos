"""Load the repository examples into a workspace, ready to open in the Studio.

For every example rule set (``examples/rulesets``): the entity with a schema inferred from its
example inputs (``examples/inputs/<entity lower case>-*.json``), the rule set with its tests
(``examples/tests/<ruleset>.tests.json``), a first published version gated by those tests and
promoted to ``prod``. Pinned sub-rulesets are published before the rule sets that use them.

An entity with a schema written by hand (``examples/entities/<entity>.json``) uses it instead of
the inferred one. Those schemas can use other entities as field types (``{"$ref":
"entity:Course"}``); they are saved after the entities they reference.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from minos.db import Entity, Workspace
from minos.schema import find_refs, infer_schema, pin_refs, resolve_refs

from . import accounts
from . import service as svc
from .errors import ControlError, NotFound
from .identity import Actor

WORKSPACE: Final = "esempi"
WORKSPACE_NAME: Final = "Esempi"
ACTOR: Final = Actor("examples", "cli")

# Friendlier names for the entities of the bundled examples; others keep their key.
ENTITY_NAMES: Final = {
    "StudyPlan": "Piano di studi",
    "Order": "Ordine",
    "LoanApplication": "Richiesta di finanziamento",
    "Student": "Studente",
    "Course": "Corso",
    "Program": "Programma",
    "Plan": "Piano individuale",
    "Enrollment": "Iscrizione",
}


@dataclass(frozen=True)
class Examples:
    graphs: list[dict[str, Any]]  # dependencies first
    samples: dict[str, list[Any]]  # entity key -> example inputs
    tests: dict[str, list[dict[str, Any]]]  # ruleset key -> test cases
    # entity key -> schema written by hand, referenced entities first
    schemas: dict[str, dict[str, Any]] = field(default_factory=dict)

    def entities(self) -> list[str]:
        """Every entity key, each after the entities its schema references."""
        return [*(e for e in self.samples if e not in self.schemas), *self.schemas]

    def resolved_schemas(self) -> dict[str, dict[str, Any]]:
        """The schema each entity gets once saved (version 1), in its resolved form."""
        out: dict[str, dict[str, Any]] = {}
        for key in self.entities():
            schema = self.schemas.get(key)
            if schema is None:
                out[key] = infer_schema(self.samples[key], title=key)
                continue
            refs = find_refs(schema)
            pinned = pin_refs(schema, {e: 1 for e, _ in refs})
            out[key] = resolve_refs(pinned, {(e, v or 1): out[e] for e, v in refs})
        return out


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _by_reference(schemas: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """``schemas`` ordered so that every entity comes after the ones it references."""
    ordered: dict[str, dict[str, Any]] = {}

    def visit(key: str, path: tuple[str, ...]) -> None:
        if key in ordered or key not in schemas:
            return
        if key in path:
            raise ValueError(f"example entities reference each other: {' -> '.join(path)}")
        for ref, _ in find_refs(schemas[key]):
            visit(ref, (*path, key))
        ordered[key] = schemas[key]

    for key in sorted(schemas):
        visit(key, ())
    return ordered


def load_examples(root: Path) -> Examples:
    """Read ``root`` (the ``examples`` directory): graphs ordered so that every pinned
    sub-ruleset comes before the rule sets that use it."""
    by_key = {g["ruleset"]: g for g in map(_read, sorted((root / "rulesets").glob("*.json")))}
    ordered: list[dict[str, Any]] = []

    def visit(key: str) -> None:
        graph = by_key[key]
        if graph in ordered:
            return
        for node in graph.get("nodes", []):
            if node.get("type") == "subruleset" and node.get("ruleset") in by_key:
                visit(node["ruleset"])
        ordered.append(graph)

    for key in by_key:
        visit(key)

    schemas = _by_reference({p.stem: _read(p) for p in sorted((root / "entities").glob("*.json"))})
    entities = {g["schemaRef"]["entity"] for g in ordered} - set(schemas)
    samples = {
        e: [_read(p) for p in sorted((root / "inputs").glob(f"{e.lower()}-*.json"))]
        for e in sorted(entities)
    }
    tests = {}
    for key in by_key:
        path = root / "tests" / f"{key}.tests.json"
        tests[key] = _read(path) if path.is_file() else []
    return Examples(ordered, samples, tests, schemas)


@dataclass(frozen=True)
class Seeded:
    published: list[str]  # ruleset@version
    skipped: list[str]  # "key: reason", for examples that do not fit this workspace


async def seed_examples(
    s: AsyncSession,
    examples: Examples,
    workspace: str = WORKSPACE,
    name: str = WORKSPACE_NAME,
) -> Seeded:
    """Publish in ``prod`` of ``workspace`` (created if missing) every example it lacks.

    Entities and rule sets that already exist, by key, are left alone, so changes made in the
    Studio survive restarts while examples added to the repository still arrive. Each example
    is added in its own savepoint: one that does not fit (e.g. a new rule set on an entity
    edited in the Studio) is skipped and reported, and never stops the others nor the start-up.
    """
    try:
        ws = await svc.get_workspace(s, svc.DEFAULT_ORGANIZATION_ID, workspace)
    except NotFound:
        org = await accounts.get_organization(s, svc.DEFAULT_ORGANIZATION)
        ws = await svc.create_workspace(s, ACTOR, org, workspace, name)

    entities = {}
    skipped: list[str] = []
    for key in examples.entities():
        try:
            entities[key] = await svc.get_entity(s, ws, key)
            continue
        except NotFound:
            pass
        try:
            async with s.begin_nested():
                entity = await svc.create_entity(
                    s, ACTOR, ws, key, ENTITY_NAMES.get(key, key), None
                )
                schema = examples.schemas.get(key)
                if schema is None and examples.samples.get(key):
                    schema = infer_schema(examples.samples[key], title=key)
                if schema is not None:
                    await svc.add_schema_version(s, ACTOR, ws, entity, schema, "examples")
            entities[key] = entity
        except ControlError as exc:
            skipped.append(f"entity {key}: {exc}")

    published = []
    for graph in examples.graphs:
        key = graph["ruleset"]
        try:
            await svc.get_ruleset(s, ws, key)
            continue
        except NotFound:
            pass
        entity_key = graph["schemaRef"]["entity"]
        if entity_key not in entities:
            skipped.append(f"{key}: entity {entity_key} was not created")
            continue
        try:
            async with s.begin_nested():
                semver = await _seed_ruleset(s, ws, entities[entity_key], graph, examples)
            published.append(f"{key}@{semver}")
        except ControlError as exc:
            skipped.append(f"{key}: {exc}")
    return Seeded(published, skipped)


async def _seed_ruleset(
    s: AsyncSession, ws: Workspace, entity: Entity, graph: dict[str, Any], examples: Examples
) -> str:
    key = graph["ruleset"]
    rs = await svc.create_ruleset(s, ACTOR, ws, entity, key, key, None, graph)
    for case in examples.tests.get(key, []):
        await svc.add_test(
            s,
            ACTOR,
            ws,
            rs,
            case["name"],
            case.get("input"),
            case.get("expected") or {},
            case.get("referenceDate"),
        )
    version, _, _ = await svc.publish(s, ACTOR, ws, rs, "minor", "Esempio", promote_to="prod")
    return version.semver
