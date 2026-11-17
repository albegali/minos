from __future__ import annotations

from typing import Any

import pytest

from minos.engine import (
    CompiledRuleset,
    CompileError,
    ExecuteOptions,
    TypeCheckError,
    compile_ruleset,
)
from minos.engine.compiler import dependencies
from minos.schema import infer_schema

from .conftest import graph

START = {"id": "start", "type": "start"}
OK = {"id": "ok", "type": "end", "outcome": "valid", "output": {"r": {"ref": "$.vars.r"}}}
KO = {"id": "ko", "type": "end", "outcome": "invalid"}


def table(rules: list[dict[str, Any]], hit: str = "first", **extra: Any) -> dict[str, Any]:
    node = {
        "id": "dt",
        "type": "decision_table",
        "hitPolicy": hit,
        "inputs": [
            {"name": "program", "expr": {"ref": "$.input.program"}},
            {"name": "cfu", "expr": {"ref": "$.input.cfu"}},
        ],
        "outputs": [{"name": "fee"}, {"name": "band"}],
        "rules": rules,
        "target": "r",
        **extra,
    }
    return graph(
        [START, node, OK, KO],
        [
            {"from": "start", "to": "dt"},
            {"from": "dt", "to": "ok", "on": "pass"},
            {"from": "dt", "to": "ko", "on": "fail"},
        ],
    )


def run(doc: dict[str, Any], data: Any, **kw: Any) -> dict[str, Any]:
    return compile_ruleset(doc, **kw).execute(data, ExecuteOptions(reference_date="2027-09-20"))


RATES = [
    {"when": ["EMBA", {"op": ">=", "value": 60}], "then": {"fee": 38500, "band": "full"}},
    {
        "when": ["EMBA", {"op": "between", "value": [30, 59]}],
        "then": {"fee": 20000, "band": "half"},
    },
    {
        "when": [["MSC", "MBA"], None],
        "then": {"fee": {"op": "*", "args": [{"ref": "$.input.cfu"}, 300]}},
    },
    {"when": ["-", "-"], "then": {"fee": 0, "band": "none"}, "priority": -1},
]


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"program": "EMBA", "cfu": 60}, {"fee": 38500, "band": "full"}),
        ({"program": "EMBA", "cfu": 40}, {"fee": 20000, "band": "half"}),
        ({"program": "MSC", "cfu": 10}, {"fee": 3000, "band": None}),
        ({"program": "OTHER", "cfu": 1}, {"fee": 0, "band": "none"}),
        ({"program": "EMBA"}, {"fee": 0, "band": "none"}),
    ],
)
def test_first_hit(data: dict[str, Any], expected: dict[str, Any]) -> None:
    r = run(table(RATES), data)
    assert r["outcome"] == "valid"
    assert r["result"]["r"] == expected


def test_no_match_follows_fail_and_records_rows() -> None:
    doc = table(RATES[:2])
    res = compile_ruleset(doc).execute({"program": "X", "cfu": 1}, ExecuteOptions(trace="full"))
    assert res["exit"]["nodeId"] == "ko"
    assert res["trace"][1]["output"] == {"rows": [], "result": None}
    res = compile_ruleset(doc).execute({"program": "EMBA", "cfu": 99}, ExecuteOptions(trace="full"))
    assert res["trace"][1]["output"]["rows"] == [1]


def test_collect_priority_unique_any() -> None:
    data = {"program": "EMBA", "cfu": 60}
    collected = run(table(RATES, "collect"), data)["result"]["r"]
    assert collected == [{"fee": 38500, "band": "full"}, {"fee": 0, "band": "none"}]
    prio = run(table(RATES, "priority"), data)["result"]["r"]
    assert prio == {"fee": 38500, "band": "full"}
    lowest = [{**RATES[0], "priority": -5}, RATES[3]]
    assert run(table(lowest, "priority"), data)["result"]["r"]["band"] == "none"

    unique = run(table(RATES, "unique"), data)
    assert unique["outcome"] == "error"
    assert "rows 1, 4" in unique["feedback"][0]["message"]
    assert run(table(RATES[:3], "unique"), data)["result"]["r"]["band"] == "full"

    agree = [RATES[0], {"when": [None, None], "then": {"fee": 38500, "band": "full"}}]
    assert run(table(agree, "any"), data)["result"]["r"]["fee"] == 38500
    disagree = run(table(RATES, "any"), data)
    assert disagree["outcome"] == "error" and "disagree" in disagree["feedback"][0]["message"]


@pytest.mark.parametrize(
    ("cell", "value", "matches"),
    [
        ({"op": "==", "value": 5}, 5, True),
        ({"op": "!=", "value": 5}, 5, False),
        ({"op": "<", "value": 5}, 4, True),
        ({"op": "<=", "value": 5}, 6, False),
        ({"op": ">", "value": 5}, None, False),
        ({"op": "in", "value": [1, 2]}, 2, True),
        ({"op": "not_in", "value": [1, 2]}, 2, False),
        ({"op": "between", "value": [1, 3]}, None, False),
        ({"op": "date_before", "value": "2027-01-01"}, "2026-12-31", True),
        ({"op": "date_after", "value": "2027-01-01"}, None, False),
        (
            {"op": "date_between", "value": ["2027-01-01", "2027-12-31"]},
            "2027-06-01T10:00:00Z",
            True,
        ),
        ({"op": "contains", "value": "b"}, "abc", True),
        ({"op": "contains", "value": "b"}, 3, False),
        ({"op": "starts_with", "value": "ab"}, "abc", True),
        ({"op": "starts_with", "value": "ab"}, 3, False),
        ({"op": ">=", "value": {"ref": "$.vars.min"}}, 7, True),
        ({"ref": "$.vars.min"}, 7, True),
        (True, True, True),
        ([{"ref": "$.vars.min"}, 9], 9, True),
    ],
)
def test_cells(cell: Any, value: Any, matches: bool) -> None:
    node = {
        "id": "dt",
        "type": "decision_table",
        "inputs": [{"name": "v", "expr": {"ref": "$.input.v"}}],
        "outputs": [{"name": "hit"}],
        "rules": [{"when": [cell], "then": {"hit": True}}],
        "target": "r",
    }
    doc = graph(
        [START, node, OK, KO],
        [
            {"from": "start", "to": "dt"},
            {"from": "dt", "to": "ok", "on": "pass"},
            {"from": "dt", "to": "ko", "on": "fail"},
        ],
        constants={"min": 7},
    )
    r = run(doc, {"v": value})
    assert (r["exit"]["nodeId"] == "ok") is matches


@pytest.mark.parametrize(
    ("cell", "value"),
    [
        ({"op": "<", "value": 5}, "x"),
        ({"op": "between", "value": [1, 5]}, "x"),
        ({"op": "in", "value": 3}, 1),
    ],
)
def test_cell_evaluation_errors(cell: Any, value: Any) -> None:
    node = {
        "id": "dt",
        "type": "decision_table",
        "inputs": [{"name": "v", "expr": {"ref": "$.input.v"}}],
        "outputs": [{"name": "hit"}],
        "rules": [{"when": [cell], "then": {"hit": True}}],
        "target": "r",
    }
    doc = graph(
        [START, node, OK], [{"from": "start", "to": "dt"}, {"from": "dt", "to": "ok", "on": "pass"}]
    )
    assert run(doc, {"v": value})["outcome"] == "error"


@pytest.mark.parametrize(
    ("rules", "outputs", "message"),
    [
        ([{"when": ["EMBA"], "then": {}}], None, "1 cell"),
        ([{"when": ["EMBA", 1], "then": {"nope": 1}}], None, "unknown output"),
        ([{"when": ["EMBA", {"op": "~", "value": 1}], "then": {}}], None, "unknown cell operator"),
        ([{"when": ["EMBA", {"op": "between", "value": 1}], "then": {}}], None, "low, high"),
        ([{"when": ["EMBA", 1], "then": {}}], [{"name": "a"}, {"name": "a"}], "duplicate output"),
    ],
)
def test_compile_errors(rules: list[Any], outputs: Any, message: str) -> None:
    doc = table(rules)
    if outputs:
        doc["nodes"][1]["outputs"] = outputs
    with pytest.raises(CompileError, match=message):
        compile_ruleset(doc)


def test_typecheck_of_tables() -> None:
    schema = infer_schema([{"program": "EMBA", "cfu": 60}])
    assert compile_ruleset(table(RATES), schema)
    bad = table(
        [
            {
                "when": ["EMBA", {"op": ">=", "value": {"ref": "$.input.nope"}}],
                "then": {"fee": {"ref": "$.input.zz"}},
            }
        ]
    )
    bad["nodes"][1]["inputs"][0]["expr"] = {"ref": "$.input.progrm"}
    with pytest.raises(TypeCheckError) as info:
        compile_ruleset(bad, schema)
    wheres = {i.where for i in info.value.issues}
    assert wheres == {
        "nodes.dt.inputs[0].expr",
        "nodes.dt.rules[0].when[1].value",
        "nodes.dt.rules[0].then.fee",
    }


# --------------------------------------------------------------------------- sub-rulesets

CHILD = graph(
    [
        START,
        {
            "id": "chk",
            "type": "condition",
            "condition": {"op": ">=", "left": {"ref": "$.input.cfu"}, "right": 6},
            "feedback": {"fail": {"code": "LOW", "message": "Troppo pochi CFU: {{input.cfu}}"}},
        },
        {
            "id": "done",
            "type": "end",
            "outcome": "valid",
            "output": {"double": {"op": "*", "args": [{"ref": "$.input.cfu"}, 2]}},
        },
    ],
    [{"from": "start", "to": "chk"}, {"from": "chk", "to": "done", "on": "pass"}],
    ruleset="t.child",
    version="1.0.0",
    settings={"mode": "collect_all"},
)


def resolver(store: dict[tuple[str, str], CompiledRuleset]) -> Any:
    def resolve(key: str, version: str) -> CompiledRuleset:
        try:
            return store[(key, version)]
        except KeyError:
            raise CompileError("not published") from None

    return resolve


def parent(**node: Any) -> dict[str, Any]:
    sub = {
        "id": "sub",
        "type": "subruleset",
        "ruleset": "t.child",
        "version": "1.0.0",
        "target": "r",
        **node,
    }
    return graph(
        [START, sub, OK, KO],
        [
            {"from": "start", "to": "sub"},
            {"from": "sub", "to": "ok", "on": "pass"},
            {"from": "sub", "to": "ko", "on": "fail"},
        ],
        settings={"mode": "collect_all"},
    )


STORE = {("t.child", "1.0.0"): compile_ruleset(CHILD)}


def test_sub_ruleset_on_the_input() -> None:
    resolve = resolver(STORE)
    r = run(parent(), {"cfu": 8}, resolve=resolve)
    assert r["outcome"] == "valid"
    assert r["result"]["r"] == {"outcome": "valid", "result": {"double": 16}}
    r = run(parent(), {"cfu": 2}, resolve=resolve)
    assert r["exit"]["nodeId"] == "ko"
    assert r["feedback"] == [
        {"code": "LOW", "severity": "error", "message": "Troppo pochi CFU: 2", "nodeId": "sub/chk"}
    ]
    r = run(parent(input={"ref": "$.input.inner"}), {"inner": {"cfu": 10}}, resolve=resolve)
    assert r["result"]["r"]["result"] == {"double": 20}


def test_sub_ruleset_for_each_element() -> None:
    resolve = resolver(STORE)
    data = {"courses": [{"cfu": 8}, {"cfu": 2}, {"cfu": 6}]}
    r = run(parent(forEach={"ref": "$.input.courses"}), data, resolve=resolve)
    assert r["exit"]["nodeId"] == "ko"
    assert r["feedback"][0]["index"] == 1
    assert r["feedback"][0]["nodeId"] == "sub/chk"
    anyone = run(parent(forEach={"ref": "$.input.courses"}, passWhen="any"), data, resolve=resolve)
    assert anyone["exit"]["nodeId"] == "ok"
    assert [x["outcome"] for x in anyone["result"]["r"]] == ["valid", "invalid", "valid"]
    # the failing element does not count when one is enough (ENG-02)
    assert (anyone["outcome"], anyone["feedback"]) == ("valid", [])
    assert (
        run(parent(forEach={"ref": "$.input.none"}), {}, resolve=resolve)["exit"]["nodeId"] == "ok"
    )
    projected = run(
        parent(forEach={"ref": "$.input.courses"}, input={"literal": {"cfu": 99}}),
        data,
        resolve=resolve,
    )
    assert projected["result"]["r"][0]["result"] == {"double": 198}
    bad = run(parent(forEach={"ref": "$.input.courses"}), {"courses": 3}, resolve=resolve)
    assert bad["outcome"] == "error"


def test_sub_ruleset_errors_and_resolution() -> None:
    with pytest.raises(CompileError, match="cannot be resolved here"):
        compile_ruleset(parent())
    with pytest.raises(CompileError, match="not published"):
        compile_ruleset(parent(version="9.9.9"), resolve=resolver(STORE))
    broken = compile_ruleset(
        graph(
            [
                START,
                {"id": "c", "type": "condition", "condition": {"op": "<", "left": "a", "right": 1}},
                {"id": "e", "type": "end", "outcome": "valid"},
            ],
            [{"from": "start", "to": "c"}, {"from": "c", "to": "e", "on": "pass"}],
            ruleset="t.broken",
            version="1.0.0",
        )
    )
    r = run(parent(ruleset="t.broken"), {}, resolve=resolver({("t.broken", "1.0.0"): broken}))
    assert r["outcome"] == "error"
    assert "sub-ruleset t.broken@1.0.0 failed" in r["feedback"][0]["message"]
    assert dependencies(parent()) == [("t.child", "1.0.0")]
    assert dependencies({"nodes": [{"type": "subruleset", "ruleset": 1}]}) == []


def test_sub_ruleset_typecheck() -> None:
    schema = infer_schema([{"courses": [{"cfu": 1}], "x": 1}])
    resolve = resolver(STORE)
    ok = parent(forEach={"ref": "$.input.courses"}, input={"ref": "$.item"})
    assert compile_ruleset(ok, schema, resolve)
    bad = parent(forEach={"ref": "$.input.corses"}, input={"ref": "$.item.cfuu"})
    with pytest.raises(TypeCheckError) as info:
        compile_ruleset(bad, schema, resolve)
    messages = [i.message for i in info.value.issues]
    assert len([m for m in messages if "corses" in m]) == 1
    typo = parent(forEach={"ref": "$.input.courses"}, input={"ref": "$.item.cfuu"})
    with pytest.raises(TypeCheckError, match="cfuu"):
        compile_ruleset(typo, schema, resolve)
    with pytest.raises(TypeCheckError, match="only be used inside"):
        compile_ruleset(parent(input={"ref": "$.item"}), schema, resolve)


def test_first_stops_at_the_first_matching_row() -> None:
    # a later row that cannot be evaluated for this input does not matter (ENG-08)
    rules = [
        {"when": ["EMBA", None], "then": {"fee": 1, "band": "a"}},
        {"when": [None, {"op": ">", "value": 5}], "then": {"fee": 2, "band": "b"}},
    ]
    r = run(table(rules), {"program": "EMBA", "cfu": "sixty"})
    assert r["outcome"] == "valid"
    assert r["result"]["r"] == {"fee": 1, "band": "a"}


def test_collect_without_matches_is_an_empty_list() -> None:
    rules = [{"when": ["EMBA", None], "then": {"fee": 1, "band": "a"}}]
    r = run(table(rules, hit="collect"), {"program": "MSC", "cfu": 1})
    assert r["exit"]["nodeId"] == "ko"
