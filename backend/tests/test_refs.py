from __future__ import annotations

import pytest

from minos.engine.errors import CompileError
from minos.engine.refs import MISSING, compile_ref, parse_path

SCOPE = {
    "input": {
        "a": {"b": 1, "odd key": 2},
        "list": [{"x": 1, "y": [10, 11]}, {"x": 2, "y": [12]}, {"z": 3}],
        "s": "str",
    },
    "vars": {"v": 5},
}


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("$.input.a.b", 1),
        ('$.input.a["odd key"]', 2),
        ("$.input.list[0].x", 1),
        ("$.input.list[-1].z", 3),
        ("$.vars.v", 5),
        ("$.input.list[*].x", [1, 2]),
        ("$.input.list[*].y[*]", [10, 11, 12]),
        ("$.input.list[*]", SCOPE["input"]["list"]),
        ("$.input.missing[*].x", []),
    ],
)
def test_resolves(path: str, expected: object) -> None:
    assert compile_ref(path)(SCOPE) == expected


@pytest.mark.parametrize(
    "path",
    ["$.input.nope", "$.input.a.b.c", "$.input.list[9]", "$.input.s.x", "$.input.a[0]", "$.item"],
)
def test_missing(path: str) -> None:
    assert compile_ref(path)(SCOPE) is MISSING


def test_root_only() -> None:
    assert compile_ref("$.vars")(SCOPE) == {"v": 5}


def test_missing_is_falsy_singleton() -> None:
    assert not MISSING
    assert repr(MISSING) == "MISSING"
    assert type(MISSING)() is MISSING


@pytest.mark.parametrize("path", ["input.a", "$.unknown.a", "$.input..a", "$.input[x]", 3])
def test_invalid_paths(path: object) -> None:
    with pytest.raises(CompileError):
        parse_path(path)  # type: ignore[arg-type]
