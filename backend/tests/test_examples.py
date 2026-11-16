"""The example rule sets must type-check against the example schema and pass their tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from minos.control.service import resolver_from
from minos.control.testing import compare
from minos.engine import ExecuteOptions, compile_ruleset
from minos.schema import infer_schema

from .conftest import EXAMPLES

GRAPHS = {p.stem: json.loads(p.read_text()) for p in sorted((EXAMPLES / "rulesets").glob("*.json"))}


def samples_for(entity: str) -> list[Any]:
    """Example inputs of an entity: ``examples/inputs/<entity lower case>-*.json``."""
    files = sorted((EXAMPLES / "inputs").glob(f"{entity.lower()}-*.json"))
    return [json.loads(p.read_text()) for p in files]


SCHEMAS = {
    g["schemaRef"]["entity"]: infer_schema(samples_for(g["schemaRef"]["entity"]))
    for g in GRAPHS.values()
}
RESOLVE = resolver_from(
    {(g["ruleset"], g["version"]): (g, SCHEMAS[g["schemaRef"]["entity"]]) for g in GRAPHS.values()}
)
SUITES = sorted((EXAMPLES / "tests").glob("*.tests.json"))


def cases() -> list[Any]:
    out = []
    for suite in SUITES:
        ruleset = suite.name.removesuffix(".tests.json")
        for case in json.loads(suite.read_text()):
            out.append(pytest.param(ruleset, case, id=f"{ruleset}: {case['name']}"))
    return out


@pytest.mark.parametrize(("ruleset", "case"), cases())
def test_example_suites(ruleset: str, case: dict[str, Any]) -> None:
    graph = GRAPHS[ruleset]
    compiled = compile_ruleset(graph, SCHEMAS[graph["schemaRef"]["entity"]], RESOLVE)
    result = compiled.execute(
        case["input"], ExecuteOptions(reference_date=case.get("referenceDate"))
    )
    assert compare(case["expected"], result) == []


def test_every_entity_has_example_inputs() -> None:
    assert all(samples_for(entity) for entity in SCHEMAS)


def test_every_example_ruleset_has_a_suite() -> None:
    rulesets = {p.stem for p in (EXAMPLES / "rulesets").glob("*.json")}
    assert rulesets == {Path(s.name.removesuffix(".tests.json")).name for s in SUITES}


def test_feedback_data_lists_offending_items() -> None:
    graph = json.loads((EXAMPLES / "rulesets" / "aurora.studyplan.common.json").read_text())
    compiled = compile_ruleset(graph, SCHEMAS["StudyPlan"])
    suite = json.loads((EXAMPLES / "tests" / "aurora.studyplan.common.tests.json").read_text())
    by_name = {c["name"]: c for c in suite}
    result = compiled.execute(by_name["corso fuori catalogo e duplicato"]["input"])
    unknown = next(f for f in result["feedback"] if f["code"] == "SP_COURSE_UNKNOWN")
    assert unknown["data"] == {"unknown": ["XXX999"]}
    result = compiled.execute(by_name["corso obbligatorio mancante"]["input"])
    missing = next(f for f in result["feedback"] if f["code"] == "SP_CORE_MISSING")
    assert missing["data"] == {"missing": ["STR110"]}
