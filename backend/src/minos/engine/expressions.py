"""Compilation of the JSON expression AST into Python closures.

An expression is one of:

* a literal (number, string, bool, null), or ``{"literal": <any JSON>}`` for objects;
* a list of expressions (evaluates to a list);
* ``{"ref": "$.input.a.b"}`` — a reference, see :mod:`minos.engine.refs`;
* ``{"op": "<operator>", "left": e, "right": e}`` or ``{"op": ..., "args": [e, ...]}``;
* ``{"fn": "<function>", "args": [e, ...], "where": e?, "select": e?}``.

Everything is compiled once, when a rule set version is published; evaluation never
parses anything. Inside ``where`` / ``select`` the current array element is ``$.item``;
in a nested aggregate the enclosing element is ``$.outer``.
"""

from __future__ import annotations

import datetime as dt
import math
import operator
import re
from collections.abc import Callable, Iterable
from typing import Any, Final

from .errors import CompileError, EvaluationError
from .refs import MISSING, Accessor, Scope, compile_ref

type Evaluator = Accessor


# --------------------------------------------------------------------------- helpers


def _is_absent(v: Any) -> bool:
    return v is MISSING or v is None


def _clean(v: Any) -> Any:
    """Turn ``MISSING`` into ``None`` so it never leaks into JSON output."""
    return None if v is MISSING else v


def to_date(v: Any) -> dt.date:
    """Coerce an ISO string, date or datetime into a :class:`datetime.date`."""
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if isinstance(v, str) and len(v) >= 10:
        try:
            return dt.date.fromisoformat(v[:10])
        except ValueError as exc:
            raise EvaluationError(f"not an ISO date: {v!r}") from exc
    raise EvaluationError(f"not a date: {v!r}")


def _const(value: Any) -> Evaluator:
    return lambda scope: value


# --------------------------------------------------------------------------- operators

_COMPARE: Final[dict[str, Callable[[Any, Any], bool]]] = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}

_ARITH: Final[dict[str, Callable[[Any, Any], Any]]] = {
    "+": operator.add,
    "-": operator.sub,
    "*": operator.mul,
    "/": operator.truediv,
    "%": operator.mod,
}


def _operands(e: dict[str, Any], where: str) -> list[Any]:
    if "args" in e:
        args = e["args"]
        if not isinstance(args, list):
            raise CompileError("'args' must be a list", where)
        return args
    out = []
    for key in ("left", "right"):
        if key in e:
            out.append(e[key])
    if "arg" in e:
        out.append(e["arg"])
    return out


def _arity(op: str, args: list[Any], n: int, where: str) -> None:
    if len(args) != n:
        raise CompileError(f"operator {op!r} expects {n} operand(s), got {len(args)}", where)


_KNOWN_OPS: Final = frozenset(
    {
        "and",
        "or",
        "not",
        "exists",
        "is_null",
        "is_not_null",
        "regex",
        "if",
        "between",
        "date_between",
        "==",
        "!=",
        "date_before",
        "date_after",
        "in",
        "not_in",
        "contains",
        "starts_with",
        "ends_with",
        *_COMPARE,
        *_ARITH,
    }
)


def _compile_op(e: dict[str, Any], where: str) -> Evaluator:
    op = e["op"]
    if op not in _KNOWN_OPS:
        raise CompileError(f"unknown operator {op!r}", where)
    raw = _operands(e, where)

    if op in ("and", "or"):
        if not raw:
            raise CompileError(f"operator {op!r} needs at least one operand", where)
        parts = tuple(compile_expr(a, f"{where}.args[{i}]") for i, a in enumerate(raw))
        if op == "and":
            return lambda s: all(bool(p(s)) for p in parts)
        return lambda s: any(bool(p(s)) for p in parts)

    if op == "not":
        _arity(op, raw, 1, where)
        inner = compile_expr(raw[0], f"{where}.arg")
        return lambda s: not bool(inner(s))

    if op in ("exists", "is_null", "is_not_null"):
        _arity(op, raw, 1, where)
        x = compile_expr(raw[0], f"{where}.arg")
        if op == "exists":
            return lambda s: x(s) is not MISSING
        if op == "is_null":
            return lambda s: _is_absent(x(s))
        return lambda s: not _is_absent(x(s))

    if op == "regex":
        _arity(op, raw, 2, where)
        if not isinstance(raw[1], str):
            raise CompileError("regex pattern must be a literal string", where)
        try:
            pattern = re.compile(raw[1])
        except re.error as exc:
            raise CompileError(f"invalid regex: {exc}", where) from exc
        subject = compile_expr(raw[0], f"{where}.left")
        return lambda s: isinstance(v := subject(s), str) and pattern.search(v) is not None

    if op == "if":
        _arity(op, raw, 3, where)
        c, t, f = (compile_expr(a, f"{where}.args[{i}]") for i, a in enumerate(raw))
        return lambda s: t(s) if c(s) else f(s)

    if op in _ARITH:
        if len(raw) < 2:
            raise CompileError(f"operator {op!r} needs at least two operands", where)
        fn = _ARITH[op]
        parts = tuple(compile_expr(a, f"{where}.args[{i}]") for i, a in enumerate(raw))

        def arith(s: Scope) -> Any:
            values = [p(s) for p in parts]
            if any(_is_absent(v) for v in values):
                return None
            acc = values[0]
            try:
                for v in values[1:]:
                    acc = fn(acc, v)
            except (TypeError, ZeroDivisionError) as exc:
                raise EvaluationError(f"{op}: {exc}") from exc
            return acc

        return arith

    _arity(op, raw, 2, where)
    left = compile_expr(raw[0], f"{where}.left")

    if op in {"between", "date_between"}:
        bounds = raw[1]
        if not isinstance(bounds, list) or len(bounds) != 2:
            raise CompileError(f"{op!r} expects 'right' to be [low, high]", where)
        lo = compile_expr(bounds[0], f"{where}.right[0]")
        hi = compile_expr(bounds[1], f"{where}.right[1]")
        conv: Callable[[Any], Any] = to_date if op == "date_between" else (lambda v: v)

        def between(s: Scope) -> bool:
            v, a, b = left(s), lo(s), hi(s)
            if _is_absent(v) or _is_absent(a) or _is_absent(b):
                return False
            try:
                return bool(conv(a) <= conv(v) <= conv(b))
            except TypeError as exc:
                raise EvaluationError(f"between: {exc}") from exc

        return between

    right = compile_expr(raw[1], f"{where}.right")

    if op in ("==", "!="):
        if _is_scalar_literal(raw[1]) and raw[1] is not None:
            # Specialised path: comparing against a non-null literal needs no MISSING
            # normalisation (the sentinel never equals a JSON scalar).
            const = raw[1]
            if op == "==":
                return lambda s: left(s) == const
            return lambda s: left(s) != const
        if op == "==":
            return lambda s: _clean(left(s)) == _clean(right(s))
        return lambda s: _clean(left(s)) != _clean(right(s))

    if op in _COMPARE:
        cmp = _COMPARE[op]

        def compare(s: Scope) -> bool:
            a, b = left(s), right(s)
            if _is_absent(a) or _is_absent(b):
                return False
            try:
                return bool(cmp(a, b))
            except TypeError as exc:
                raise EvaluationError(f"cannot compare {a!r} {op} {b!r}") from exc

        return compare

    if op in ("date_before", "date_after"):
        cmp = operator.lt if op == "date_before" else operator.gt

        def date_cmp(s: Scope) -> bool:
            a, b = left(s), right(s)
            if _is_absent(a) or _is_absent(b):
                return False
            return bool(cmp(to_date(a), to_date(b)))

        return date_cmp

    if op in ("in", "not_in"):
        negate: bool = op == "not_in"
        literal = (
            raw[1]
            if isinstance(raw[1], list) and all(not isinstance(x, (dict, list)) for x in raw[1])
            else None
        )
        if literal is not None:
            frozen = frozenset(x for x in literal if x is not None and _hashable(x))
            if len(frozen) == len(literal):
                return lambda s: (_clean(left(s)) in frozen) != negate

        def member(s: Scope) -> bool:
            container = right(s)
            if not isinstance(container, (list, str, dict)):
                return negate
            return (_clean(left(s)) in container) != negate

        return member

    if op == "contains":

        def contains(s: Scope) -> bool:
            container, needle = left(s), right(s)
            if isinstance(container, (list, str)):
                try:
                    return needle in container
                except TypeError:
                    return False
            return False

        return contains

    if op in ("starts_with", "ends_with"):
        method = str.startswith if op == "starts_with" else str.endswith

        def affix(s: Scope) -> bool:
            a, b = left(s), right(s)
            return isinstance(a, str) and isinstance(b, str) and method(a, b)

        return affix

    raise AssertionError(f"operator {op!r} not handled")  # pragma: no cover


def _is_scalar_literal(x: Any) -> bool:
    return x is None or isinstance(x, (bool, int, float, str))


def _hashable(x: Any) -> bool:
    try:
        hash(x)
    except TypeError:
        return False
    return True


# --------------------------------------------------------------------------- functions

_AGGREGATES: Final = frozenset(
    {"sum", "count", "min", "max", "avg", "any", "all", "distinct", "filter", "map"}
)


_STRING_FNS: Final[dict[str, Callable[[str], str]]] = {
    "lower": lambda v: v.lower(),
    "upper": lambda v: v.upper(),
    "trim": lambda v: v.strip(),
}


def _numbers(values: Iterable[Any], fn: str) -> list[Any]:
    out = [v for v in values if not _is_absent(v)]
    for v in out:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise EvaluationError(f"{fn}: non-numeric value {v!r}")
    return out


def _compile_fn(e: dict[str, Any], where: str) -> Evaluator:
    name = e["fn"]
    raw = e.get("args", [])
    if not isinstance(raw, list):
        raise CompileError("'args' must be a list", where)
    args = tuple(compile_expr(a, f"{where}.args[{i}]") for i, a in enumerate(raw))

    if name in _AGGREGATES:
        if len(args) != 1:
            raise CompileError(f"function {name!r} expects exactly one array argument", where)
        source = args[0]
        pred = compile_expr(e["where"], f"{where}.where") if "where" in e else None
        select = compile_expr(e["select"], f"{where}.select") if "select" in e else None

        def items(s: Scope) -> list[Any]:
            seq = source(s)
            if _is_absent(seq):
                return []
            if not isinstance(seq, list):
                raise EvaluationError(f"{name}: expected an array, got {type(seq).__name__}")
            if pred is None and select is None:
                return seq
            # Bind $.item in place (no scope copy per element) and restore it afterwards,
            # so nested aggregates see their own element.
            # The enclosing aggregate's element (if any) becomes $.outer.
            previous = s.get("item", MISSING)
            previous_outer = s.get("outer", MISSING)
            if previous is not MISSING:
                s["outer"] = previous
            out: list[Any] = []
            try:
                for x in seq:
                    s["item"] = x
                    if pred is not None and not pred(s):
                        continue
                    out.append(select(s) if select is not None else x)
            finally:
                for key, value in (("item", previous), ("outer", previous_outer)):
                    if value is MISSING:
                        s.pop(key, None)
                    else:
                        s[key] = value
            return out

        if name == "count":
            return lambda s: len(items(s))
        if name == "sum":
            return lambda s: sum(_numbers(items(s), "sum"))
        if name in ("min", "max"):
            agg = min if name == "min" else max

            def minmax(s: Scope) -> Any:
                vals = _numbers(items(s), name)
                return agg(vals) if vals else None

            return minmax
        if name == "avg":

            def avg(s: Scope) -> Any:
                vals = _numbers(items(s), "avg")
                return sum(vals) / len(vals) if vals else None

            return avg
        if name == "any":
            return lambda s: any(bool(x) for x in items(s))
        if name == "all":
            return lambda s: all(bool(x) for x in items(s))
        if name == "distinct":

            def distinct(s: Scope) -> list[Any]:
                seen: list[Any] = []
                for x in items(s):
                    if x not in seen:
                        seen.append(x)
                return seen

            return distinct
        # filter / map: the shaped list itself
        return items

    def single(n: int) -> None:
        if len(args) != n:
            raise CompileError(f"function {name!r} expects {n} argument(s)", where)

    if name == "len":
        single(1)
        (x,) = args

        def length(s: Scope) -> Any:
            v = x(s)
            return len(v) if isinstance(v, (list, str, dict)) else None

        return length
    if name in ("lower", "upper", "trim"):
        single(1)
        (x,) = args
        method = _STRING_FNS[name]
        return lambda s: method(v) if isinstance(v := x(s), str) else None
    if name == "coalesce":
        if not args:
            raise CompileError("coalesce needs at least one argument", where)

        def coalesce(s: Scope) -> Any:
            for a in args:
                v = a(s)
                if not _is_absent(v):
                    return v
            return None

        return coalesce
    if name == "round":
        if len(args) not in (1, 2):
            raise CompileError("round expects 1 or 2 arguments", where)

        def rnd(s: Scope) -> Any:
            v = args[0](s)
            if _is_absent(v):
                return None
            digits = args[1](s) if len(args) == 2 else 0
            try:
                return round(v, digits) if digits else round(v)
            except TypeError as exc:
                raise EvaluationError(f"round: {exc}") from exc

        return rnd
    if name == "abs":
        single(1)
        (x,) = args
        return lambda s: None if _is_absent(v := x(s)) else abs(v)
    if name == "floor":
        single(1)
        (x,) = args
        return lambda s: None if _is_absent(v := x(s)) else math.floor(v)
    if name == "date":
        single(1)
        (x,) = args
        return lambda s: None if _is_absent(v := x(s)) else to_date(v).isoformat()
    if name == "today":
        single(0)
        return lambda s: s["meta"]["referenceDate"]
    if name == "days_between":
        single(2)
        a, b = args

        def days(s: Scope) -> Any:
            x, y = a(s), b(s)
            if _is_absent(x) or _is_absent(y):
                return None
            return (to_date(y) - to_date(x)).days

        return days
    if name == "age":
        if len(args) not in (1, 2):
            raise CompileError("age expects 1 or 2 arguments", where)

        def age(s: Scope) -> Any:
            born = args[0](s)
            if _is_absent(born):
                return None
            ref = to_date(args[1](s) if len(args) == 2 else s["meta"]["referenceDate"])
            b = to_date(born)
            return ref.year - b.year - ((ref.month, ref.day) < (b.month, b.day))

        return age

    raise CompileError(f"unknown function {name!r}", where)


# --------------------------------------------------------------------------- entry point


def compile_expr(e: Any, where: str = "expr") -> Evaluator:
    """Compile an expression AST into a closure ``scope -> value``."""
    if isinstance(e, dict):
        if "ref" in e:
            try:
                return compile_ref(e["ref"])
            except CompileError as exc:
                raise CompileError(exc.message, where) from exc
        if "op" in e:
            return _compile_op(e, where)
        if "fn" in e:
            return _compile_fn(e, where)
        if "literal" in e:
            return _const(e["literal"])
        raise CompileError(f"unrecognised expression keys {sorted(e)}", where)
    if isinstance(e, list):
        parts = tuple(compile_expr(x, f"{where}[{i}]") for i, x in enumerate(e))
        return lambda s: [_clean(p(s)) for p in parts]
    if e is None or isinstance(e, (bool, int, float, str)):
        return _const(e)
    raise CompileError(f"unsupported literal {e!r}", where)


def clean(value: Any) -> Any:
    """Public helper: replace the ``MISSING`` sentinel with ``None``."""
    return _clean(value)
