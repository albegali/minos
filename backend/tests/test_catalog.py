"""The editor catalogue must describe exactly what the compiler accepts."""

from __future__ import annotations

from typing import Any

import pytest

from minos.engine import CompileError
from minos.engine.catalog import FUNCTIONS, OPERATORS, catalog
from minos.engine.expressions import _KNOWN_OPS, compile_expr
from minos.engine.model import RuleGraph
from minos.engine.refs import ROOTS
from minos.engine.typecheck import META_KEYS


def test_operators_match_the_compiler() -> None:
    assert {o["op"] for o in OPERATORS} == set(_KNOWN_OPS)


def _args(spec: Any) -> list[Any]:
    n = {"1+": 1, "1-2": 1}.get(spec, spec)
    return ["2027-01-01"] * int(n)


@pytest.mark.parametrize("fn", FUNCTIONS, ids=lambda f: f["fn"])
def test_every_function_compiles(fn: dict[str, Any]) -> None:
    if fn.get("aggregate"):
        compile_expr({"fn": fn["fn"], "args": [[1, 2]]})
    else:
        compile_expr({"fn": fn["fn"], "args": _args(fn["args"])})


def test_unknown_function_is_rejected() -> None:
    with pytest.raises(CompileError):
        compile_expr({"fn": "nope", "args": []})


def test_node_types_cover_the_model() -> None:
    cat = catalog()
    types = {n["type"] for n in cat["nodeTypes"]}
    union = RuleGraph.model_json_schema()["$defs"]
    assert types == {"start", "condition", "group", "set", "switch", "feedback", "end"}
    assert {d.removesuffix("Node").lower() for d in union if d.endswith("Node")} - {""} == types
    for n in cat["nodeTypes"]:
        assert "id" not in n["params"]["properties"]
        assert "type" not in n["params"]["properties"]
        assert n["category"] in {c["key"] for c in cat["categories"]}
        assert set(n["requiredPorts"]) <= set(n["ports"])
    assert set(cat["roots"]) == set(ROOTS)
    assert set(cat["metaKeys"]) == set(META_KEYS)
    condition = next(n for n in cat["nodeTypes"] if n["type"] == "condition")
    assert condition["params"]["required"] == ["condition"]
