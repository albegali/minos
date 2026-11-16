"""Compilation of JSON path references (``$.input.courses[*].cfu``) into fast accessors.

Supported syntax, deliberately small so it can be compiled ahead of time:

* ``$.<root>`` where root is one of :data:`ROOTS`;
* ``.key`` for object members (``["key"]`` for keys with special characters);
* ``[n]`` for array indexes (negative indexes count from the end);
* ``[*]`` to fan out over every element of an array (the result is then a list).

Filters such as JSONPath ``[?(...)]`` are expressed with the ``where`` clause of
aggregate functions instead (see :mod:`minos.engine.expressions`).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Final

from .errors import CompileError


class _Missing:
    """Sentinel for a path that does not exist in the scope."""

    _instance: _Missing | None = None

    def __new__(cls) -> _Missing:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "MISSING"


MISSING: Final = _Missing()

type Scope = dict[str, Any]
type Accessor = Callable[[Scope], Any]

ROOTS: Final = frozenset({"input", "vars", "nodes", "meta", "item"})

_TOKEN = re.compile(
    r"""
    \.(?P<key>[A-Za-z_][A-Za-z0-9_\-]*)     # .key
    | \[(?P<index>-?\d+)\]                  # [3]
    | \[(?P<star>\*)\]                      # [*]
    | \["(?P<qkey>[^"]+)"\]                 # ["odd key"]
    """,
    re.VERBOSE,
)

_STAR: Final = object()

type Segment = str | int | object


def parse_path(path: str) -> tuple[str, tuple[Segment, ...]]:
    """Split ``$.root.a[0][*].b`` into ``("root", ("a", 0, STAR, "b"))``."""
    if not isinstance(path, str) or not path.startswith("$."):
        raise CompileError(f"reference must start with '$.': {path!r}")
    pos = 1
    segments: list[Segment] = []
    while pos < len(path):
        m = _TOKEN.match(path, pos)
        if m is None:
            raise CompileError(f"invalid reference syntax at char {pos}: {path!r}")
        if m.group("key") is not None:
            segments.append(m.group("key"))
        elif m.group("qkey") is not None:
            segments.append(m.group("qkey"))
        elif m.group("index") is not None:
            segments.append(int(m.group("index")))
        else:
            segments.append(_STAR)
        pos = m.end()
    if not segments or not isinstance(segments[0], str) or segments[0] not in ROOTS:
        raise CompileError(f"reference root must be one of {sorted(ROOTS)}: {path!r}")
    root = segments[0]
    assert isinstance(root, str)
    return root, tuple(segments[1:])


def _step(value: Any, seg: Segment) -> Any:
    if isinstance(seg, str):
        if isinstance(value, dict):
            return value.get(seg, MISSING)
        return MISSING
    if isinstance(seg, int):
        if isinstance(value, list):
            try:
                return value[seg]
            except IndexError:
                return MISSING
        return MISSING
    raise AssertionError("unreachable")  # pragma: no cover


def compile_ref(path: str) -> Accessor:
    """Return a function ``scope -> value`` for ``path``; absent paths yield ``MISSING``."""
    root, segments = parse_path(path)

    if _STAR not in segments:
        keys = segments
        if not keys:
            return lambda scope: scope.get(root, MISSING)
        if len(keys) == 1 and isinstance(keys[0], str):
            k0 = keys[0]

            def get1(scope: Scope) -> Any:
                v = scope.get(root, MISSING)
                return v.get(k0, MISSING) if isinstance(v, dict) else MISSING

            return get1

        def get(scope: Scope) -> Any:
            v = scope.get(root, MISSING)
            for seg in keys:
                if v is MISSING:
                    return MISSING
                v = _step(v, seg)
            return v

        return get

    def get_many(scope: Scope) -> Any:
        current: list[Any] = [scope.get(root, MISSING)]
        for seg in segments:
            nxt: list[Any] = []
            if seg is _STAR:
                for v in current:
                    if isinstance(v, list):
                        nxt.extend(v)
            else:
                for v in current:
                    r = _step(v, seg)
                    if r is not MISSING:
                        nxt.append(r)
            current = nxt
        return current

    return get_many
