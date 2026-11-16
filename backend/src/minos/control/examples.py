"""Load the repository examples into a workspace, ready to open in the Studio.

For every example rule set (``examples/rulesets``): the entity with a schema inferred from its
example inputs (``examples/inputs/<entity lower case>-*.json``), the rule set with its tests
(``examples/tests/<ruleset>.tests.json``), a first published version gated by those tests and
promoted to ``prod``. Pinned sub-rulesets are published before the rule sets that use them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from minos.schema import infer_schema

from . import service as svc
from .errors import NotFound

WORKSPACE: Final = "esempi"
WORKSPACE_NAME: Final = "Esempi"
ACTOR: Final = "examples"

# Friendlier names for the entities of the bundled examples; others keep their key.
ENTITY_NAMES: Final = {
    "StudyPlan": "Piano di studi",
    "Order": "Ordine",
    "LoanApplication": "Richiesta di finanziamento",
}


@dataclass(frozen=True)
class Examples:
    graphs: list[dict[str, Any]]  # dependencies first
    samples: dict[str, list[Any]]  # entity key -> example inputs
    tests: dict[str, list[dict[str, Any]]]  # ruleset key -> test cases


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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

    entities = {g["schemaRef"]["entity"] for g in ordered}
    samples = {
        e: [_read(p) for p in sorted((root / "inputs").glob(f"{e.lower()}-*.json"))]
        for e in sorted(entities)
    }
    tests = {}
    for key in by_key:
        path = root / "tests" / f"{key}.tests.json"
        tests[key] = _read(path) if path.is_file() else []
    return Examples(ordered, samples, tests)


async def seed_examples(
    s: AsyncSession,
    examples: Examples,
    workspace: str = WORKSPACE,
    name: str = WORKSPACE_NAME,
) -> list[str] | None:
    """Create ``workspace`` with every example published in ``prod``.

    Returns the published ``ruleset@version`` list, or ``None`` when the workspace already
    exists (nothing is touched, so changes made in the Studio survive restarts).
    """
    try:
        await svc.get_workspace(s, workspace)
        return None
    except NotFound:
        pass
    ws = await svc.create_workspace(s, ACTOR, workspace, name)

    entities = {}
    for key, samples in examples.samples.items():
        entity = await svc.create_entity(s, ACTOR, ws, key, ENTITY_NAMES.get(key, key), None)
        if samples:
            schema = infer_schema(samples, title=key)
            await svc.add_schema_version(s, ACTOR, ws, entity, schema, "examples")
        entities[key] = entity

    published = []
    for graph in examples.graphs:
        key = graph["ruleset"]
        entity = entities[graph["schemaRef"]["entity"]]
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
        version, _ = await svc.publish(s, ACTOR, ws, rs, "minor", "Esempio", promote_to="prod")
        published.append(f"{key}@{version.semver}")
    return published
