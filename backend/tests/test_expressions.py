from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from minos.engine.errors import CompileError, EvaluationError
from minos.engine.expressions import compile_expr, to_date

SCOPE: dict[str, Any] = {
    "input": {
        "n": 5,
        "f": 2.5,
        "s": "Hello",
        "date": "2027-09-20T10:15:00Z",
        "nul": None,
        "tags": ["a", "b"],
        "courses": [
            {"area": "FIN", "cfu": 6, "type": "CORE"},
            {"area": "FIN", "cfu": 4, "type": "ELECTIVE"},
            {"area": "STR", "cfu": 8, "type": "ELECTIVE"},
        ],
        "born": "1990-04-12",
    },
    "vars": {"lo": 1, "hi": 10, "allowed": [1, 2, 3]},
    "meta": {"referenceDate": "2027-09-20"},
}


def ev(expr: Any) -> Any:
    return compile_expr(expr)(SCOPE)


def ref(path: str) -> dict[str, str]:
    return {"ref": path}


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        (5, 5),
        ("x", "x"),
        (None, None),
        ({"literal": {"a": 1}}, {"a": 1}),
        ([1, ref("$.input.n"), ref("$.input.none")], [1, 5, None]),
        ({"op": "==", "left": ref("$.input.n"), "right": 5}, True),
        ({"op": "==", "left": ref("$.input.none"), "right": None}, True),
        ({"op": "==", "left": ref("$.input.n"), "right": ref("$.input.n")}, True),
        ({"op": "!=", "left": ref("$.input.n"), "right": 4}, True),
        ({"op": "!=", "left": ref("$.input.n"), "right": ref("$.vars.lo")}, True),
        ({"op": ">", "left": ref("$.input.n"), "right": 4}, True),
        ({"op": "<=", "left": ref("$.input.f"), "right": 2.5}, True),
        ({"op": "<", "left": ref("$.input.none"), "right": 4}, False),
        (
            {
                "op": "between",
                "left": ref("$.input.n"),
                "right": [ref("$.vars.lo"), ref("$.vars.hi")],
            },
            True,
        ),
        ({"op": "between", "left": ref("$.input.none"), "right": [1, 2]}, False),
        (
            {
                "op": "date_between",
                "left": ref("$.input.date"),
                "right": ["2027-09-01", "2027-09-20"],
            },
            True,
        ),
        ({"op": "date_before", "left": ref("$.input.date"), "right": "2027-10-01"}, True),
        ({"op": "date_after", "left": ref("$.input.date"), "right": "2027-10-01"}, False),
        ({"op": "date_after", "left": ref("$.input.none"), "right": "2027-10-01"}, False),
        ({"op": "in", "left": ref("$.input.n"), "right": [4, 5]}, True),
        ({"op": "in", "left": 2, "right": ref("$.vars.allowed")}, True),
        ({"op": "not_in", "left": 9, "right": ref("$.vars.allowed")}, True),
        ({"op": "in", "left": 9, "right": ref("$.input.none")}, False),
        ({"op": "in", "left": 1, "right": [1, 1]}, True),
        ({"op": "contains", "left": ref("$.input.tags"), "right": "a"}, True),
        ({"op": "contains", "left": ref("$.input.s"), "right": "ell"}, True),
        ({"op": "contains", "left": ref("$.input.n"), "right": "x"}, False),
        ({"op": "contains", "left": ref("$.input.s"), "right": 3}, False),
        ({"op": "starts_with", "left": ref("$.input.s"), "right": "He"}, True),
        ({"op": "ends_with", "left": ref("$.input.s"), "right": "lo"}, True),
        ({"op": "regex", "left": ref("$.input.s"), "right": "^H.l+o$"}, True),
        ({"op": "regex", "left": ref("$.input.n"), "right": "5"}, False),
        ({"op": "exists", "arg": ref("$.input.nul")}, True),
        ({"op": "exists", "arg": ref("$.input.none")}, False),
        ({"op": "is_null", "arg": ref("$.input.nul")}, True),
        ({"op": "is_not_null", "arg": ref("$.input.n")}, True),
        ({"op": "and", "args": [True, {"op": ">", "left": ref("$.input.n"), "right": 1}]}, True),
        ({"op": "or", "args": [False, False]}, False),
        ({"op": "not", "arg": False}, True),
        ({"op": "if", "args": [True, "yes", "no"]}, "yes"),
        ({"op": "if", "args": [False, "yes", "no"]}, "no"),
        ({"op": "+", "args": [1, 2, 3]}, 6),
        ({"op": "-", "left": 10, "right": 4}, 6),
        ({"op": "*", "args": [ref("$.input.n"), 2]}, 10),
        ({"op": "/", "args": [10, 4]}, 2.5),
        ({"op": "%", "args": [10, 4]}, 2),
        ({"op": "+", "args": [1, ref("$.input.none")]}, None),
    ],
)
def test_operators(expr: Any, expected: Any) -> None:
    assert ev(expr) == expected


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ({"fn": "sum", "args": [ref("$.input.courses[*].cfu")]}, 18),
        ({"fn": "count", "args": [ref("$.input.courses")]}, 3),
        ({"fn": "count", "args": [ref("$.input.none")]}, 0),
        (
            {
                "fn": "sum",
                "args": [ref("$.input.courses")],
                "where": {"op": "==", "left": ref("$.item.area"), "right": "FIN"},
                "select": ref("$.item.cfu"),
            },
            10,
        ),
        ({"fn": "min", "args": [ref("$.input.courses[*].cfu")]}, 4),
        ({"fn": "max", "args": [ref("$.input.courses[*].cfu")]}, 8),
        ({"fn": "max", "args": [[]]}, None),
        ({"fn": "avg", "args": [ref("$.input.courses[*].cfu")]}, 6),
        ({"fn": "avg", "args": [[]]}, None),
        ({"fn": "any", "args": [[False, True]]}, True),
        ({"fn": "all", "args": [[True, False]]}, False),
        (
            {
                "fn": "all",
                "args": [ref("$.input.courses")],
                "select": {"op": ">", "left": ref("$.item.cfu"), "right": 3},
            },
            True,
        ),
        ({"fn": "distinct", "args": [ref("$.input.courses[*].area")]}, ["FIN", "STR"]),
        (
            {
                "fn": "filter",
                "args": [ref("$.input.courses")],
                "where": {"op": "==", "left": ref("$.item.area"), "right": "STR"},
            },
            [{"area": "STR", "cfu": 8, "type": "ELECTIVE"}],
        ),
        (
            {"fn": "map", "args": [ref("$.input.courses")], "select": ref("$.item.type")},
            ["CORE", "ELECTIVE", "ELECTIVE"],
        ),
        ({"fn": "len", "args": [ref("$.input.s")]}, 5),
        ({"fn": "len", "args": [ref("$.input.n")]}, None),
        ({"fn": "lower", "args": [ref("$.input.s")]}, "hello"),
        ({"fn": "upper", "args": [ref("$.input.n")]}, None),
        ({"fn": "trim", "args": ["  x "]}, "x"),
        ({"fn": "coalesce", "args": [ref("$.input.none"), ref("$.input.nul"), 7]}, 7),
        ({"fn": "coalesce", "args": [ref("$.input.none")]}, None),
        ({"fn": "round", "args": [2.567, 2]}, 2.57),
        ({"fn": "round", "args": [2.5]}, 2),
        ({"fn": "round", "args": [ref("$.input.none")]}, None),
        ({"fn": "abs", "args": [-3]}, 3),
        ({"fn": "floor", "args": [2.9]}, 2),
        ({"fn": "date", "args": [ref("$.input.date")]}, "2027-09-20"),
        ({"fn": "today", "args": []}, "2027-09-20"),
        ({"fn": "days_between", "args": ["2027-09-01", ref("$.input.date")]}, 19),
        ({"fn": "days_between", "args": [ref("$.input.none"), "2027-09-01"]}, None),
        ({"fn": "age", "args": [ref("$.input.born")]}, 37),
        ({"fn": "age", "args": [ref("$.input.born"), "2027-04-11"]}, 36),
        ({"fn": "age", "args": [ref("$.input.none")]}, None),
    ],
)
def test_functions(expr: Any, expected: Any) -> None:
    assert ev(expr) == expected


def test_nested_item_scopes_are_restored() -> None:
    expr = {
        "fn": "count",
        "args": [ref("$.input.courses")],
        "where": {
            "op": ">",
            "left": {
                "fn": "count",
                "args": [ref("$.input.courses")],
                "where": {"op": "==", "left": ref("$.item.area"), "right": "FIN"},
            },
            "right": 1,
        },
    }
    scope = dict(SCOPE)
    assert compile_expr(expr)(scope) == 3
    assert "item" not in scope
    scope["item"] = "outer"
    compile_expr(expr)(scope)
    assert scope["item"] == "outer"


@pytest.mark.parametrize(
    "expr",
    [
        {"op": "nope", "left": 1, "right": 2},
        {"op": "and", "args": []},
        {"op": "and", "args": 3},
        {"op": "not", "args": [1, 2]},
        {"op": "between", "left": 1, "right": [1]},
        {"op": "regex", "left": "a", "right": {"ref": "$.input.s"}},
        {"op": "regex", "left": "a", "right": "("},
        {"op": "+", "args": [1]},
        {"fn": "nope", "args": []},
        {"fn": "sum", "args": [1, 2]},
        {"fn": "sum", "args": 1},
        {"fn": "len", "args": []},
        {"fn": "coalesce", "args": []},
        {"fn": "round", "args": []},
        {"fn": "age", "args": []},
        {"ref": "input.x"},
        {"what": 1},
        {"op": "==", "left": {"ref": "$.bad.x"}, "right": 1},
        object(),
    ],
)
def test_compile_errors(expr: Any) -> None:
    with pytest.raises(CompileError):
        compile_expr(expr)


@pytest.mark.parametrize(
    "expr",
    [
        {"op": "<", "left": ref("$.input.s"), "right": 1},
        {"op": "/", "args": [1, 0]},
        {"op": "between", "left": ref("$.input.s"), "right": [1, 2]},
        {"op": "date_before", "left": "not a date", "right": "2027-01-01"},
        {"op": "date_before", "left": 5, "right": "2027-01-01"},
        {"fn": "sum", "args": [ref("$.input.s")]},
        {"fn": "sum", "args": [ref("$.input.tags")]},
        {"fn": "round", "args": ["x"]},
    ],
)
def test_evaluation_errors(expr: Any) -> None:
    with pytest.raises(EvaluationError):
        ev(expr)


def test_to_date_accepts_dates() -> None:
    assert to_date(dt.date(2027, 1, 2)) == dt.date(2027, 1, 2)
    assert to_date(dt.datetime(2027, 1, 2, 3, 4)) == dt.date(2027, 1, 2)


def test_outer_binds_the_enclosing_element() -> None:
    # for each area, the CFU of the courses in that area
    expr = {
        "fn": "map",
        "args": [["FIN", "STR"]],
        "select": {
            "fn": "sum",
            "args": [ref("$.input.courses")],
            "where": {"op": "==", "left": ref("$.item.area"), "right": ref("$.outer")},
            "select": ref("$.item.cfu"),
        },
    }
    scope = dict(SCOPE)
    assert compile_expr(expr)(scope) == [10, 8]
    assert "outer" not in scope and "item" not in scope
