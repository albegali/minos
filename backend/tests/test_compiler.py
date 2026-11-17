from __future__ import annotations

import functools
from typing import Any

import pytest

from minos.engine import CompileError, compile_ruleset, graph_hash
from minos.engine.model import RuleGraph
from minos.engine.templates import compile_template

from .conftest import graph

START = {"id": "start", "type": "start"}
END = {"id": "end", "type": "end", "outcome": "valid"}
COND = {"id": "c", "type": "condition", "condition": True}


def test_aurora_example_compiles(aurora_graph: dict[str, Any]) -> None:
    compiled = compile_ruleset(aurora_graph)
    assert compiled.ruleset == "aurora.studyplan.emba"
    assert compiled.mode == "collect_all"
    assert compiled.warnings == ()
    assert len(compiled.hash) == 64


def test_compiles_from_model(aurora_graph: dict[str, Any]) -> None:
    model = RuleGraph.model_validate(aurora_graph)
    assert compile_ruleset(model).ruleset == "aurora.studyplan.emba"


def test_hash_ignores_ui_but_not_logic(aurora_graph: dict[str, Any]) -> None:
    moved = dict(aurora_graph, ui={"positions": {"start": [5, 5]}})
    assert graph_hash(moved) == graph_hash(aurora_graph)
    changed = dict(aurora_graph, constants={**aurora_graph["constants"], "minCfu": 61})
    assert graph_hash(changed) != graph_hash(aurora_graph)


def test_unreachable_nodes_are_warnings() -> None:
    doc = graph(
        [START, END, {"id": "orphan", "type": "end", "outcome": "invalid"}],
        [{"from": "start", "to": "end"}],
    )
    assert compile_ruleset(doc).warnings == ("node 'orphan' is unreachable from start",)


@pytest.mark.parametrize(
    ("nodes", "edges", "message"),
    [
        (
            [START, END],
            [{"from": "start", "to": "end"}, {"from": "start", "to": "end"}],
            "connected twice",
        ),
        ([START, START, END], [], "duplicate node id"),
        ([START, {**START, "id": "s2"}, END], [], "exactly one start"),
        ([START, COND], [], "at least one end"),
        ([START, END], [{"from": "x", "to": "end"}], "unknown source"),
        ([START, END], [{"from": "start", "to": "x"}], "unknown target"),
        ([START, END], [{"from": "start", "to": "start"}], "start node"),
        ([START, END], [{"from": "start", "to": "end", "on": "pass"}], "has no port"),
        ([START, END], [], "unconnected port"),
        (
            [START, END, {**END, "id": "e2"}],
            [{"from": "start", "to": "end"}, {"from": "end", "to": "e2"}],
            "has no port",
        ),
        (
            [START, COND, END],
            [{"from": "start", "to": "c"}, {"from": "c", "to": "end", "on": "fail"}],
            "unconnected port",
        ),
        (
            [START, COND, {**COND, "id": "d"}, END],
            [
                {"from": "start", "to": "c"},
                {"from": "c", "to": "d", "on": "pass"},
                {"from": "d", "to": "c", "on": "pass"},
                {"from": "d", "to": "end", "on": "fail"},
            ],
            "cycle detected",
        ),
        (
            [START, {**COND, "onFail": "branch"}, END],
            [{"from": "start", "to": "c"}, {"from": "c", "to": "end", "on": "pass"}],
            "requires a connected 'fail' port",
        ),
        (
            [START, {**COND, "condition": {"op": "bogus"}}, END],
            [{"from": "start", "to": "c"}, {"from": "c", "to": "end", "on": "pass"}],
            "unknown operator",
        ),
        (
            [START, {**COND, "feedback": {"fail": {"code": "X", "message": "{{bad.root}}"}}}, END],
            [{"from": "start", "to": "c"}, {"from": "c", "to": "end", "on": "pass"}],
            "bad placeholder",
        ),
        (
            [START, {**COND, "feedback": {"fail": {"code": "X", "message": {}}}}, END],
            [{"from": "start", "to": "c"}, {"from": "c", "to": "end", "on": "pass"}],
            "cannot be empty",
        ),
        ([START, {"id": "e", "type": "teleport"}], [], "does not match any of the expected tags"),
    ],
)
def test_invalid_graphs(nodes: list[Any], edges: list[Any], message: str) -> None:
    with pytest.raises(CompileError, match=message):
        compile_ruleset(graph(nodes, edges))


def test_cycle_unreachable_from_start_is_detected() -> None:
    nodes = [START, END, {**COND, "id": "a"}, {**COND, "id": "b"}]
    edges = [
        {"from": "start", "to": "end"},
        {"from": "a", "to": "b", "on": "pass"},
        {"from": "b", "to": "a", "on": "pass"},
    ]
    with pytest.raises(CompileError, match="cycle"):
        compile_ruleset(graph(nodes, edges))


def test_compile_error_str_contains_location() -> None:
    err = CompileError("boom", "nodes.x")
    assert str(err) == "nodes.x: boom"
    assert str(CompileError("boom")) == "boom"


def test_templates() -> None:
    scope = {"vars": {"a": 1.0, "b": True, "c": None, "d": 2.5}}
    assert compile_template("static")(scope) == "static"
    assert compile_template("{{vars.a}}|{{ vars.b }}|{{vars.c}}|{{vars.d}}|{{vars.x}}!")(scope) == (
        "1|true||2.5|!"
    )


@pytest.mark.parametrize(
    "condition",
    [
        {"op": ["=="], "left": 1, "right": 1},
        {"fn": ["len"], "args": ["x"]},
        # deeper than Python's recursion allows while compiling
        functools.reduce(lambda acc, _: {"op": "not", "arg": acc}, range(2000), True),
    ],
)
def test_malformed_graphs_are_compile_errors(condition: Any) -> None:
    # ENG-04: never an unexpected exception (HTTP 500 on validate/publish)
    doc = graph(
        [
            {"id": "start", "type": "start"},
            {"id": "c", "type": "condition", "condition": condition},
            {"id": "ok", "type": "end", "outcome": "valid"},
        ],
        [{"from": "start", "to": "c"}, {"from": "c", "to": "ok", "on": "pass"}],
    )
    with pytest.raises(CompileError):
        compile_ruleset(doc)


def test_malformed_group_child_is_a_compile_error() -> None:
    doc = graph(
        [
            {"id": "start", "type": "start"},
            {
                "id": "g",
                "type": "group",
                "operator": "and",
                "children": [{"rule": True, "feedback": {"fail": {"code": "X"}}}],
            },
            {"id": "ok", "type": "end", "outcome": "valid"},
        ],
        [{"from": "start", "to": "g"}, {"from": "g", "to": "ok", "on": "pass"}],
    )
    with pytest.raises(CompileError):
        compile_ruleset(doc)
