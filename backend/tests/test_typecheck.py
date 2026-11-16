from __future__ import annotations

import json
from typing import Any

import pytest

from minos.engine import TypeCheckError, compile_ruleset
from minos.schema import infer_schema

from .conftest import graph

SCHEMA = infer_schema(
    [
        {
            "n": 1,
            "name": "x",
            "flag": True,
            "when": "2027-01-01",
            "tags": ["a"],
            "courses": [{"cfu": 6, "area": "FIN", "lessons": [{"hours": 2}]}],
            "nested": {"deep": {"v": 1}},
        }
    ]
)

START = {"id": "start", "type": "start"}
END = {"id": "end", "type": "end", "outcome": "valid"}


def one(condition: Any, **extra: Any) -> dict[str, Any]:
    nodes = [START, {"id": "c", "type": "condition", "condition": condition}, END]
    edges = [{"from": "start", "to": "c"}, {"from": "c", "to": "end", "on": "pass"}]
    return graph(nodes, edges, **extra)


def issues(doc: dict[str, Any], schema: dict[str, Any] | None = SCHEMA) -> list[str]:
    try:
        compile_ruleset(doc, schema)
    except TypeCheckError as exc:
        return [i.message for i in exc.issues]
    return []


def ref(p: str) -> dict[str, str]:
    return {"ref": p}


def test_gsom_example_is_clean(
    gsom_graph: dict[str, Any], valid_plan: dict[str, Any], invalid_plan: dict[str, Any]
) -> None:
    schema = infer_schema([valid_plan, invalid_plan])
    assert issues(gsom_graph, schema) == []


@pytest.mark.parametrize(
    "condition",
    [
        {"op": ">", "left": ref("$.input.n"), "right": 3},
        {"op": "==", "left": "x", "right": ref("$.input.name")},
        {"op": "==", "left": ref("$.input.when"), "right": "2027-01-01"},
        {"op": "==", "left": ref("$.input.name"), "right": None},
        {"op": "in", "left": ref("$.input.name"), "right": ["a", "b"]},
        {"op": "==", "left": ref("$.input.n"), "right": ref("$.input.name")},
        {"op": ">", "left": {"fn": "sum", "args": [ref("$.input.courses[*].cfu")]}, "right": 1},
        {
            "op": ">",
            "left": {
                "fn": "count",
                "args": [ref("$.input.courses")],
                "where": {"op": "==", "left": ref("$.item.area"), "right": "FIN"},
            },
            "right": 0,
        },
        {
            "op": ">",
            "left": {"fn": "sum", "args": [ref("$.input.courses[*].lessons[*].hours")]},
            "right": 0,
        },
        {
            "fn": "any",
            "args": [ref("$.input.courses")],
            "select": {
                "op": ">",
                "left": {
                    "fn": "sum",
                    "args": [ref("$.item.lessons")],
                    "select": ref("$.item.hours"),
                },
                "right": 1,
            },
        },
        {
            "fn": "count",
            "args": [{"fn": "filter", "args": [ref("$.input.tags")]}],
            "where": {"op": "==", "left": ref("$.item"), "right": "a"},
        },
        {"op": "==", "left": ref("$.input.courses[0].area"), "right": "FIN"},
        {"op": "==", "left": ref("$.meta.locale"), "right": "it"},
        {"op": "==", "left": ref("$.nodes.c.outcome"), "right": "pass"},
        {"op": "and", "args": [ref("$.input.flag"), {"op": "not", "arg": ref("$.input.flag")}]},
        {"op": "if", "args": [ref("$.input.flag"), 1, 2]},
        {"op": "==", "left": ref("$.input.nested.deep.v"), "right": 1},
    ],
)
def test_valid_references(condition: Any) -> None:
    assert issues(one(condition)) == []


@pytest.mark.parametrize(
    ("condition", "message"),
    [
        ({"op": ">", "left": ref("$.input.nn"), "right": 3}, "$.input.nn does not exist"),
        ({"op": ">", "left": ref("$.input.nested.deep.w"), "right": 3}, "does not exist"),
        ({"op": ">", "left": ref("$.input.name"), "right": 3}, "type string with a number"),
        ({"op": "==", "left": 3, "right": ref("$.input.name")}, "always false"),
        ({"op": "!=", "left": ref("$.input.flag"), "right": "x"}, "always true"),
        ({"op": "==", "left": ref("$.input.n"), "right": True}, "boolean literal"),
        ({"fn": "sum", "args": [ref("$.input.name")]}, "sum() needs an array"),
        ({"fn": "sum", "args": [ref("$.input.tags")]}, "sum() needs numbers"),
        (
            {
                "fn": "count",
                "args": [ref("$.input.courses")],
                "where": {"op": "==", "left": ref("$.item.areaa"), "right": "FIN"},
            },
            "$.item.areaa does not exist in the array element schema",
        ),
        ({"op": "==", "left": ref("$.item.x"), "right": 1}, "only be used inside"),
        ({"op": "==", "left": ref("$.vars.nope"), "right": 1}, "variable 'nope'"),
        ({"op": "==", "left": ref("$.nodes.zz.outcome"), "right": 1}, "node 'zz' does not exist"),
        ({"op": "==", "left": ref("$.meta.who"), "right": 1}, "unknown metadata key"),
        ({"fn": "len", "args": [ref("$.input.zz")]}, "does not exist"),
        ({"op": "and", "args": [[ref("$.input.zz")]]}, "does not exist"),
    ],
)
def test_reported_issues(condition: Any, message: str) -> None:
    found = issues(one(condition))
    assert found, "expected an issue"
    assert any(message in m for m in found), found


def test_untyped_item_scope_is_not_checked() -> None:
    cond = {
        "fn": "count",
        "args": [{"fn": "filter", "args": [ref("$.input.courses")]}],
        "where": {"op": "==", "left": ref("$.item.whatever"), "right": 1},
    }
    assert issues(one(cond)) == []


def test_without_schema_only_internal_references_are_checked() -> None:
    assert issues(one({"op": ">", "left": ref("$.input.anything"), "right": 3}), None) == []
    assert issues(one({"op": ">", "left": ref("$.vars.x"), "right": 3}), None)


def test_every_location_is_checked() -> None:
    bad = ref("$.input.zz")
    doc = graph(
        [
            START,
            {
                "id": "g",
                "type": "group",
                "operator": "and",
                "children": [
                    bad,
                    {
                        "rule": bad,
                        "feedback": {
                            "fail": {
                                "code": "X",
                                "message": {"it": "{{input.zz}}"},
                                "data": {"d": bad},
                            }
                        },
                    },
                ],
                "feedback": {"fail": {"code": "Y", "message": "{{vars.nope}}", "data": {"d": bad}}},
            },
            {"id": "s", "type": "set", "assign": {"v": bad}},
            {"id": "sw", "type": "switch", "cases": [{"name": "a", "when": bad}]},
            {
                "id": "f",
                "type": "feedback",
                "when": bad,
                "feedback": {"code": "F", "message": "{{input.zz}}", "data": {"d": bad}},
            },
            {"id": "end", "type": "end", "outcome": "valid", "output": {"o": bad}},
        ],
        [
            {"from": "start", "to": "g"},
            {"from": "g", "to": "s", "on": "pass"},
            {"from": "s", "to": "sw"},
            {"from": "sw", "to": "f", "on": "a"},
            {"from": "sw", "to": "f", "on": "default"},
            {"from": "f", "to": "end"},
        ],
        constants={"k": bad},
    )
    with pytest.raises(TypeCheckError) as info:
        compile_ruleset(doc, SCHEMA)
    wheres = {i.where for i in info.value.issues}
    assert {
        "constants.k",
        "nodes.g.children[0]",
        "nodes.g.children[1].rule",
        "nodes.g.children[1].feedback.fail.message.it",
        "nodes.g.children[1].feedback.fail.data.d",
        "nodes.g.feedback.fail.message",
        "nodes.g.feedback.fail.data.d",
        "nodes.s.assign.v",
        "nodes.sw.cases.a",
        "nodes.f.when",
        "nodes.f.feedback.message",
        "nodes.f.feedback.data.d",
        "nodes.end.output.o",
    } <= wheres
    assert "(+" in str(info.value)
    assert info.value.issues[0].as_dict().keys() == {"where", "message"}
    json.dumps([i.as_dict() for i in info.value.issues])


def test_outer_scope() -> None:
    nested = {
        "fn": "all",
        "args": [ref("$.input.courses")],
        "select": {
            "op": ">=",
            "left": {
                "fn": "count",
                "args": [ref("$.input.courses")],
                "where": {"op": "==", "left": ref("$.item.area"), "right": ref("$.outer.area")},
            },
            "right": 1,
        },
    }
    assert issues(one(nested)) == []
    typo = json.loads(json.dumps(nested).replace("$.outer.area", "$.outer.aera"))
    assert any("aera" in m for m in issues(one(typo)))
    flat = {
        "fn": "count",
        "args": [ref("$.input.courses")],
        "where": {"op": "==", "left": ref("$.outer.area"), "right": "FIN"},
    }
    assert any("nested aggregate" in m for m in issues(one(flat)))
