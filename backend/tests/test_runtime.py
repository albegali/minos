from __future__ import annotations

from typing import Any

import pytest

from minos.engine import ExecuteOptions, ExecutionLimitError, compile_ruleset

from .conftest import graph

START = {"id": "start", "type": "start"}
OK = {"id": "ok", "type": "end", "outcome": "valid", "output": {"n": {"ref": "$.input.n"}}}
KO = {"id": "ko", "type": "end", "outcome": "invalid"}


def fb(code: str, severity: str = "error", message: Any = "msg") -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message}


def check(nid: str, expr: Any, **extra: Any) -> dict[str, Any]:
    return {"id": nid, "type": "condition", "condition": expr, **extra}


def gt(n: int) -> dict[str, Any]:
    return {"op": ">", "left": {"ref": "$.input.n"}, "right": n}


def chain(*nodes: dict[str, Any], mode: str = "fail_fast") -> dict[str, Any]:
    """start -> nodes... -> ok, connecting each node's pass/next port."""
    edges = []
    prev, port = "start", "next"
    for n in nodes:
        edges.append({"from": prev, "to": n["id"], "on": port})
        prev, port = n["id"], ("pass" if n["type"] in ("condition", "group") else "next")
    edges.append({"from": prev, "to": "ok", "on": port})
    return graph([START, *nodes, OK], edges, settings={"mode": mode})


def run(doc: dict[str, Any], data: Any, **opts: Any) -> dict[str, Any]:
    return compile_ruleset(doc).execute(data, ExecuteOptions(reference_date="2027-09-20", **opts))


def test_aurora_valid(aurora_graph: dict[str, Any], valid_plan: dict[str, Any]) -> None:
    r = run(aurora_graph, valid_plan)
    assert r["outcome"] == "valid"
    assert r["result"] == {"totalCfu": 60, "electiveCfu": 12, "tuitionFee": 30800}
    assert [f["code"] for f in r["feedback"]] == ["SP_WINDOW_OK"]
    assert "chkFinTrack" in r["path"]


def test_aurora_invalid_collects_everything(
    aurora_graph: dict[str, Any], invalid_plan: dict[str, Any]
) -> None:
    r = run(aurora_graph, invalid_plan, locale="en")
    assert r["outcome"] == "invalid"
    assert r["exit"] == {"nodeId": "endOk", "reason": "end"}
    codes = [f["code"] for f in r["feedback"]]
    assert codes == [
        "SP_WINDOW_OK",
        "SP_CFU_MIN",
        "SP_ELECTIVE_MAX",
        "SP_FIN_LIMIT",
        "SP_INSTALLMENTS",
    ]
    cfu = r["feedback"][1]
    assert cfu["message"] == "At least 60 ECTS required, found 40"
    assert cfu["data"] == {"actual": 40, "required": 60}
    assert cfu["path"] == "courses"


def test_aurora_window_closed_stops(
    aurora_graph: dict[str, Any], valid_plan: dict[str, Any]
) -> None:
    r = run(aurora_graph, {**valid_plan, "submittedAt": "2027-11-01T00:00:00Z"})
    assert r["outcome"] == "invalid"
    assert r["exit"] == {"nodeId": "chkWindow", "reason": "stop"}
    assert r["path"] == ["start", "derive", "chkWindow"]
    assert r["feedback"][0]["message"] == (
        "La finestra di presentazione va dal 2027-09-01 al 2027-10-15"
    )


def test_fail_fast_stops_at_first_failure() -> None:
    doc = chain(check("a", gt(10), feedback={"fail": fb("A")}), check("b", gt(20)))
    r = run(doc, {"n": 1})
    assert r["outcome"] == "invalid"
    assert r["exit"] == {"nodeId": "a", "reason": "stop"}
    assert r["path"] == ["start", "a"]


def test_collect_all_continues_and_downgrades_outcome() -> None:
    doc = chain(
        check("a", gt(10)), check("b", gt(20), feedback={"fail": fb("B")}), mode="collect_all"
    )
    r = run(doc, {"n": 1})
    assert r["path"] == ["start", "a", "b", "ok"]
    assert r["outcome"] == "invalid"
    assert r["result"] == {"n": 1}


def test_warnings_make_outcome_warning() -> None:
    doc = chain(check("a", gt(10), feedback={"fail": fb("W", "warning")}), mode="collect_all")
    doc["nodes"][1]["onFail"] = "continue"
    r = run(doc, {"n": 1})
    assert r["outcome"] == "invalid"  # a continued failure is still a failure

    doc = chain({"id": "w", "type": "feedback", "feedback": fb("W", "warning")})
    assert run(doc, {"n": 1})["outcome"] == "warning"


def test_feedback_on_pass_and_locale_fallback() -> None:
    doc = chain(
        check(
            "a", gt(0), feedback={"pass": fb("P", "info", {"it": "ok {{input.n}}", "en": "fine"})}
        )
    )
    assert run(doc, {"n": 3})["feedback"][0]["message"] == "ok 3"
    assert run(doc, {"n": 3}, locale="en")["feedback"][0]["message"] == "fine"
    assert run(doc, {"n": 3}, locale="de")["feedback"][0]["message"] == "ok 3"
    doc["nodes"][1]["feedback"]["pass"]["message"] = {"fr": "bien"}
    assert run(doc, {"n": 3})["feedback"][0]["message"] == "bien"


def test_branching_on_fail_is_control_flow_not_failure() -> None:
    doc = graph(
        [START, check("a", gt(10)), OK, {"id": "small", "type": "end", "outcome": "valid"}],
        [
            {"from": "start", "to": "a"},
            {"from": "a", "to": "ok", "on": "pass"},
            {"from": "a", "to": "small", "on": "fail"},
        ],
    )
    r = run(doc, {"n": 1})
    assert r["outcome"] == "valid"
    assert r["exit"]["nodeId"] == "small"


def test_explicit_fail_edge_with_continue_records_failure() -> None:
    doc = graph(
        [START, check("a", gt(10), onFail="continue"), OK, KO],
        [
            {"from": "start", "to": "a"},
            {"from": "a", "to": "ok", "on": "pass"},
            {"from": "a", "to": "ko", "on": "fail"},
        ],
    )
    r = run(doc, {"n": 1})
    assert r["outcome"] == "invalid"
    assert r["exit"]["nodeId"] == "ko"


@pytest.mark.parametrize(
    ("operator", "evaluate", "n", "passed", "evaluated"),
    [
        ("and", "short_circuit", 1, False, [False]),
        ("and", "all", 1, False, [False, True]),
        ("and", "all", 50, True, [True, True]),
        ("or", "short_circuit", 50, True, [True]),
        ("or", "all", 1, True, [False, True]),
        ("not", "short_circuit", 1, True, [False]),
        ("not", "all", 50, False, [True, True]),
    ],
)
def test_groups(operator: str, evaluate: str, n: int, passed: bool, evaluated: list[bool]) -> None:
    group = {
        "id": "g",
        "type": "group",
        "operator": operator,
        "evaluate": evaluate,
        "children": [
            {"rule": gt(10), "feedback": {"fail": fb("C1")}},
            {"op": ">", "left": {"ref": "$.input.n"}, "right": 0},
        ],
        "onFail": "continue",
        "feedback": {"fail": fb("G"), "pass": fb("GP", "info")},
    }
    r = run(chain(group, mode="collect_all"), {"n": n}, trace="full")
    entry = r["trace"][1]
    assert entry["outcome"] == ("pass" if passed else "fail")
    assert entry["output"] == evaluated
    codes = [f["code"] for f in r["feedback"]]
    assert ("GP" in codes) == passed
    # a child's failure is reported only when it makes the group fail
    assert ("C1" in codes) == (False in evaluated[:1] and not passed)


def test_switch_and_set_nodes() -> None:
    doc = graph(
        [
            START,
            {
                "id": "s",
                "type": "set",
                "assign": {"double": {"op": "*", "args": [{"ref": "$.input.n"}, 2]}},
            },
            {"id": "sw", "type": "switch", "cases": [{"name": "big", "when": gt(10)}]},
            {
                "id": "big",
                "type": "end",
                "outcome": "valid",
                "output": {"d": {"ref": "$.vars.double"}},
            },
            {
                "id": "small",
                "type": "end",
                "outcome": "invalid",
                "output": {"d": {"ref": "$.vars.double"}},
            },
        ],
        [
            {"from": "start", "to": "s"},
            {"from": "s", "to": "sw"},
            {"from": "sw", "to": "big", "on": "big"},
            {"from": "sw", "to": "small", "on": "default"},
        ],
    )
    assert run(doc, {"n": 20})["result"] == {"d": 40}
    r = run(doc, {"n": 2}, trace="summary")
    assert r["result"] == {"d": 4}
    assert r["outcome"] == "invalid"
    assert [t["nodeId"] for t in r["trace"]] == ["start", "s", "sw", "small"]
    assert r["trace"][2]["port"] == "default"


def test_feedback_node_when() -> None:
    node = {"id": "f", "type": "feedback", "feedback": fb("F", "info"), "when": gt(10)}
    assert run(chain(node), {"n": 1})["feedback"] == []
    assert run(chain(node), {"n": 11})["feedback"][0]["code"] == "F"


def test_node_outputs_are_visible_to_later_nodes() -> None:
    doc = chain(
        check("a", gt(0)),
        check("b", {"op": "==", "left": {"ref": "$.nodes.a.outcome"}, "right": "pass"}),
    )
    assert run(doc, {"n": 1})["outcome"] == "valid"


def test_evaluation_error_ends_with_error() -> None:
    doc = chain(check("a", {"op": ">", "left": {"ref": "$.input.n"}, "right": "x"}))
    r = run(doc, {"n": 1}, trace="summary")
    assert r["outcome"] == "error"
    assert r["exit"] == {"nodeId": "a", "reason": "error"}
    assert r["feedback"][0]["code"] == "MINOS_EVALUATION_ERROR"
    assert r["trace"][-1]["outcome"] == "error"


def test_max_steps() -> None:
    doc = chain(check("a", True), check("b", True))
    doc["settings"]["maxSteps"] = 2
    with pytest.raises(ExecutionLimitError):
        run(doc, {"n": 1})


def test_defaults_and_metadata() -> None:
    compiled = compile_ruleset(chain(check("a", True)))
    r = compiled.execute({"n": 1})
    assert r["trace"] is None
    assert len(r["requestId"]) == 32
    assert r["timing"]["engineUs"] >= 0
    r = compiled.execute({"n": 1}, ExecuteOptions(request_id="abc"))
    assert r["requestId"] == "abc"


def test_group_child_failures_are_reported_only_when_the_group_fails() -> None:
    # "passport or ID card": one alternative is enough (ENG-01)
    group = {
        "id": "docs",
        "type": "group",
        "operator": "or",
        "evaluate": "all",
        "children": [
            {
                "rule": {"op": "exists", "arg": {"ref": "$.input.passport"}},
                "feedback": {"fail": fb("NO_PASSPORT")},
            },
            {
                "rule": {"op": "exists", "arg": {"ref": "$.input.idCard"}},
                "feedback": {"fail": fb("NO_ID")},
            },
        ],
    }
    doc = chain(group, mode="collect_all")
    r = run(doc, {"idCard": "X"})
    assert (r["outcome"], r["feedback"]) == ("valid", [])
    r = run(doc, {})
    assert r["outcome"] == "invalid"
    assert [f["code"] for f in r["feedback"]] == ["NO_PASSPORT", "NO_ID"]

    negated = {**group, "operator": "not", "children": group["children"][:1]}
    r = run(chain(negated, mode="collect_all"), {})
    assert (r["outcome"], r["feedback"]) == ("valid", [])


@pytest.mark.parametrize(
    ("expr", "data"),
    [
        ({"op": "in", "left": {"ref": "$.input.v"}, "right": ["a", "b"]}, {"v": ["x"]}),
        ({"op": "in", "left": {"ref": "$.input.v"}, "right": "abc"}, {"v": 1}),
        ({"fn": "abs", "args": [{"ref": "$.input.v"}]}, {"v": "x"}),
        ({"fn": "floor", "args": [{"op": "*", "args": [{"ref": "$.input.v"}, 10]}]}, {"v": 1e308}),
        ({"op": "%", "args": [{"ref": "$.input.v"}, 1]}, {"v": "%z"}),
    ],
)
def test_unexpected_values_end_with_error_not_a_crash(expr: Any, data: Any) -> None:
    # without schema validation any value can reach an expression (ENG-03)
    r = run(chain(check("c", expr)), data)
    assert r["outcome"] == "error"
    assert r["feedback"][0]["code"] == "MINOS_EVALUATION_ERROR"


def test_end_output_errors_end_with_error() -> None:
    end = {
        "id": "ok",
        "type": "end",
        "outcome": "valid",
        "output": {"q": {"op": "/", "args": [1, {"ref": "$.input.z"}]}},
    }
    doc = graph([START, end], [{"from": "start", "to": "ok"}])
    r = run(doc, {"z": 0})
    assert (r["outcome"], r["exit"]) == ("error", {"nodeId": "ok", "reason": "error"})
