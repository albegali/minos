"""Decision tables: rows of input tests and output values, with a hit policy.

Cells (one per input column):

* ``null`` or ``"-"`` — any value;
* a scalar — equality;
* a list — the value is one of the items (items may be expressions);
* ``{"op": "<op>", "value": <value or expression>}`` — a test with an operator of
  :data:`CELL_OPS` (``between`` / ``date_between`` take ``[low, high]``);
* an expression object (``{"ref": ...}``, ``{"fn": ...}``) — equality with its value.

Hit policies: ``first`` (first matching row), ``unique`` (exactly one row may match),
``priority`` (highest ``priority`` wins, ties go to the first), ``any`` (all matching rows
must agree), ``collect`` (every matching row, as a list).
"""

from __future__ import annotations

import operator
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from .errors import CompileError, EvaluationError
from .expressions import Evaluator, clean, compile_expr, json_key, same, to_date
from .refs import MISSING, Scope

type Cell = Callable[[Any, Scope], bool]

_ORDER: Final[dict[str, Callable[[Any, Any], bool]]] = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}

CELL_OPS: Final = frozenset(
    {
        "==",
        "!=",
        *_ORDER,
        "in",
        "not_in",
        "between",
        "date_before",
        "date_after",
        "date_between",
        "contains",
        "starts_with",
    }
)


def _absent(v: Any) -> bool:
    return v is None or v is MISSING


def _compile_cell(cell: Any, where: str) -> Cell | None:
    if cell is None or cell == "-":
        return None
    if isinstance(cell, list):
        items = tuple(compile_expr(x, f"{where}[{i}]") for i, x in enumerate(cell))
        return lambda v, s: clean(v) in [clean(i(s)) for i in items]
    if isinstance(cell, dict) and "op" in cell and "value" in cell:
        return _compile_test(cell["op"], cell["value"], where)
    if isinstance(cell, (dict, str, int, float, bool)):
        expected = compile_expr(cell, where)
        return lambda v, s: clean(v) == clean(expected(s))
    raise CompileError(f"unsupported cell {cell!r}", where)  # pragma: no cover - not JSON


def _compile_test(op: str, raw: Any, where: str) -> Cell:
    if op not in CELL_OPS:
        raise CompileError(f"unknown cell operator {op!r} (allowed: {sorted(CELL_OPS)})", where)
    if op in ("between", "date_between"):
        if not isinstance(raw, list) or len(raw) != 2:
            raise CompileError(f"{op!r} needs [low, high]", where)
        lo, hi = (compile_expr(x, f"{where}.value[{i}]") for i, x in enumerate(raw))
        conv: Callable[[Any], Any] = to_date if op == "date_between" else (lambda x: x)

        def between(v: Any, s: Scope) -> bool:
            a, b = lo(s), hi(s)
            if _absent(v) or _absent(a) or _absent(b):
                return False
            try:
                return bool(conv(a) <= conv(v) <= conv(b))
            except TypeError as exc:
                raise EvaluationError(f"cell {op}: {exc}") from exc

        return between

    value = compile_expr(raw, f"{where}.value")
    if op == "==":
        return lambda v, s: same(v, value(s))
    if op == "!=":
        return lambda v, s: not same(v, value(s))
    if op in _ORDER:
        cmp = _ORDER[op]

        def order(v: Any, s: Scope) -> bool:
            r = value(s)
            if _absent(v) or _absent(r):
                return False
            try:
                return bool(cmp(v, r))
            except TypeError as exc:
                raise EvaluationError(f"cell: cannot compare {v!r} {op} {r!r}") from exc

        return order
    if op in ("in", "not_in"):
        negate = op == "not_in"

        def member(v: Any, s: Scope) -> bool:
            r = value(s)
            if not isinstance(r, list):
                raise EvaluationError(f"cell {op}: expected a list, got {r!r}")
            return (json_key(v) in {json_key(x) for x in r}) != negate

        return member
    if op in ("date_before", "date_after"):
        cmp = operator.lt if op == "date_before" else operator.gt

        def date_cmp(v: Any, s: Scope) -> bool:
            r = value(s)
            if _absent(v) or _absent(r):
                return False
            return bool(cmp(to_date(v), to_date(r)))

        return date_cmp
    if op == "contains":

        def contains(v: Any, s: Scope) -> bool:
            needle = value(s)
            if isinstance(v, str):
                return isinstance(needle, str) and needle in v
            if isinstance(v, list):
                return json_key(needle) in {json_key(x) for x in v}
            return False

        return contains
    # starts_with
    return lambda v, s: isinstance(v, str) and isinstance(r := value(s), str) and v.startswith(r)


@dataclass(frozen=True, slots=True)
class _Row:
    index: int
    cells: tuple[Cell | None, ...]
    then: tuple[tuple[str, Evaluator], ...]
    priority: float


@dataclass(frozen=True, slots=True)
class DecisionTable:
    hit_policy: str
    inputs: tuple[Evaluator, ...]
    outputs: tuple[str, ...]
    rows: tuple[_Row, ...]

    def evaluate(self, scope: Scope) -> tuple[list[int], Any]:
        """Return ``(matched row indexes, result)``; result is ``None`` when nothing matched."""
        values = [ev(scope) for ev in self.inputs]
        matched = [
            row
            for row in self.rows
            if all(cell is None or cell(values[i], scope) for i, cell in enumerate(row.cells))
        ]
        indexes = [r.index for r in matched]
        if not matched:
            return indexes, None
        if self.hit_policy == "collect":
            return indexes, [self._out(r, scope) for r in matched]
        if self.hit_policy == "first":
            return indexes[:1], self._out(matched[0], scope)
        if self.hit_policy == "priority":
            best = max(matched, key=lambda r: (r.priority, -r.index))
            return [best.index], self._out(best, scope)
        if self.hit_policy == "unique":
            if len(matched) > 1:
                rows = ", ".join(str(i + 1) for i in indexes)
                raise EvaluationError(f"hit policy 'unique' violated: rows {rows} all match")
            return indexes, self._out(matched[0], scope)
        # any: every matching row must produce the same output
        outs = [self._out(r, scope) for r in matched]
        if any(o != outs[0] for o in outs[1:]):
            rows = ", ".join(str(i + 1) for i in indexes)
            raise EvaluationError(f"hit policy 'any' violated: rows {rows} disagree")
        return indexes, outs[0]

    def _out(self, row: _Row, scope: Scope) -> dict[str, Any]:
        values = {name: clean(ev(scope)) for name, ev in row.then}
        return {name: values.get(name) for name in self.outputs}


def compile_table(
    hit_policy: str,
    inputs: list[Any],
    outputs: list[str],
    rules: list[Any],
    where: str,
) -> DecisionTable:
    """Compile a decision table; ``inputs`` are expressions, ``rules`` RGD rule models."""
    compiled_inputs = tuple(
        compile_expr(e, f"{where}.inputs[{i}].expr") for i, e in enumerate(inputs)
    )
    names = set(outputs)
    if len(names) != len(outputs):
        raise CompileError("duplicate output column names", f"{where}.outputs")
    rows = []
    for i, rule in enumerate(rules):
        rw = f"{where}.rules[{i}]"
        if len(rule.when) != len(inputs):
            raise CompileError(
                f"row {i + 1} has {len(rule.when)} cell(s) for {len(inputs)} input column(s)", rw
            )
        unknown = set(rule.then) - names
        if unknown:
            raise CompileError(f"unknown output column(s) {sorted(unknown)}", f"{rw}.then")
        cells = tuple(_compile_cell(c, f"{rw}.when[{j}]") for j, c in enumerate(rule.when))
        then = tuple((k, compile_expr(v, f"{rw}.then.{k}")) for k, v in rule.then.items())
        rows.append(_Row(i, cells, then, rule.priority))
    return DecisionTable(hit_policy, compiled_inputs, tuple(outputs), tuple(rows))
