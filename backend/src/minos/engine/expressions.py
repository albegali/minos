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
from collections.abc import Callable, Iterable
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Final

import re2

from .errors import CompileError, EvaluationError
from .refs import MISSING, Accessor, Scope, compile_ref

# Rule patterns run against untrusted input: RE2 matches in linear time, so no pattern can
# make a request backtrack for seconds (ReDoS). Pattern errors become compile errors.
_RE2_OPTIONS = re2.Options()
_RE2_OPTIONS.log_errors = False

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
        # The whole text must be an ISO date or date-time ("2027-09-20garbage" is not); a
        # date-time counts for the date written in it, in its own offset.
        try:
            if len(v) == 10:
                return dt.date.fromisoformat(v)
            return dt.datetime.fromisoformat(v).date()
        except ValueError as exc:
            raise EvaluationError(f"not an ISO date: {v[:40]!r}") from exc
    raise EvaluationError(f"not a date: {str(v)[:40]!r}")


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
        search = _compile_pattern(raw[1], where)
        subject = compile_expr(raw[0], f"{where}.left")
        return lambda s: isinstance(v := subject(s), str) and search(v)

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
            if not all(_is_number(v) for v in values) and not (
                op == "+" and _same_sequence_kind(values)
            ):
                # Only numbers, and `+` on texts or lists: `"x" * n` or `"%9999999d" % 1` would
                # let an input value allocate gigabytes.
                kinds = ", ".join(sorted({_kind(v) for v in values}))
                raise EvaluationError(f"{op}: operands must be numbers, got {kinds}")
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
            test = _equals_literal(left, raw[1])
            if op == "==":
                return test
            return lambda s: not test(s)
        if op == "==":
            return lambda s: same(left(s), right(s))
        return lambda s: not same(left(s), right(s))

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
        if isinstance(raw[1], list) and not any(isinstance(x, dict) for x in raw[1]):
            # A literal list (no expressions in it): its keys are computed once, here.
            values = raw[1]
            if all(isinstance(x, str) for x in values):  # the common case: codes, names
                texts = frozenset(values)
                return lambda s: (type(v := left(s)) is str and v in texts) != negate
            frozen = frozenset(json_key(x) for x in values)
            return lambda s: (json_key(left(s)) in frozen) != negate

        def member(s: Scope) -> bool:
            container, needle = right(s), left(s)
            if isinstance(container, list):
                if type(needle) is str and len(container) <= _SCAN_LIMIT:
                    found = needle in container  # a text only equals a text: no keys needed
                else:
                    found = json_key(needle) in _key_set(s, container)
            elif isinstance(container, (str, dict)):
                found = isinstance(needle, str) and needle in container
            else:
                return negate
            return found != negate

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


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _same_sequence_kind(values: list[Any]) -> bool:
    return all(isinstance(v, str) for v in values) or all(isinstance(v, list) for v in values)


def _kind(v: Any) -> str:
    if isinstance(v, bool):
        return "boolean"
    if _is_number(v):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def json_key(v: Any) -> Any:
    """Hashable key with JSON equality: ``1 == 1.0`` but ``true != 1``; lists and objects by
    content. Used for ``==``, ``in`` and ``distinct``."""
    if v is None or v is MISSING:
        return None
    if isinstance(v, bool):
        return ("b", v)
    if isinstance(v, (int, float)):
        return ("n", v)
    if isinstance(v, str):
        return ("s", v)
    if isinstance(v, list):
        return ("l", tuple(json_key(x) for x in v))
    if isinstance(v, dict):
        return ("o", tuple(sorted((k, json_key(x)) for k, x in v.items())))
    return ("x", repr(v))


def _compile_pattern(pattern: str, where: str) -> Callable[[str], bool]:
    """``text -> found`` for a rule pattern, matched by RE2 anywhere in the text."""
    try:
        compiled = re2.compile(pattern, _RE2_OPTIONS)
    except re2.error as exc:
        detail = exc.args[0].decode() if exc.args and isinstance(exc.args[0], bytes) else exc
        raise CompileError(
            f"invalid regex: {detail} (RE2 syntax: no backreferences or lookarounds)", where
        ) from exc
    native = getattr(compiled, "_regexp", None)
    anchor = getattr(getattr(re2, "_re2", None), "RE2", None)
    if native is None or anchor is None:  # pragma: no cover - other google-re2 versions
        return lambda text: compiled.search(text) is not None
    # The native matcher directly: the public wrapper costs ~4x more per call (rules run it
    # once per item of an aggregate).
    unanchored = anchor.Anchor.UNANCHORED

    def search(text: str) -> bool:
        data = text.encode()
        return bool(native.Match(unanchored, data, 0, len(data))[0][0] != -1)

    return search


def _equals_literal(left: Evaluator, const: Any) -> Evaluator:
    """``left == const`` for a non-null JSON scalar, with JSON equality and no allocation."""
    if isinstance(const, bool):
        return lambda s: left(s) is const
    if isinstance(const, str):
        return lambda s: left(s) == const
    if const not in (0, 1):  # only 0 and 1 equal a boolean in Python
        return lambda s: left(s) == const
    return lambda s: (v := left(s)) == const and v is not True and v is not False


def same(a: Any, b: Any) -> bool:
    """JSON equality of two values (``MISSING`` equals ``null``)."""
    ta, tb = type(a), type(b)
    if ta is tb and ta in (str, int, float):
        return bool(a == b)
    return bool(json_key(a) == json_key(b))


# Up to this length a list is scanned directly; beyond, its keys are hashed once per execution.
_SCAN_LIMIT: Final = 32


def _key_set(s: Scope, container: list[Any]) -> frozenset[Any]:
    """Keys of ``container``, computed once per execution (``in`` inside an aggregate would
    otherwise scan the list once per item: quadratic on large inputs)."""
    memo: dict[int, tuple[list[Any], frozenset[Any]]] = s.setdefault("_memo", {})
    hit = memo.get(id(container))
    if hit is not None and hit[0] is container:
        return hit[1]
    keys = frozenset(json_key(x) for x in container)
    memo[id(container)] = (container, keys)  # keeping the list alive keeps its id unique
    return keys


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
        if name in ("any", "all") and pred is not None and select is None:
            # `where` alone is the test: "any course with cfu >= 6", "all courses with ...".
            def matching(s: Scope) -> bool:
                seq = source(s)
                total = len(seq) if isinstance(seq, list) else 0
                matched = len(items(s))
                return matched > 0 if name == "any" else matched == total

            return matching
        if name == "any":
            return lambda s: any(bool(x) for x in items(s))
        if name == "all":
            return lambda s: all(bool(x) for x in items(s))
        if name == "distinct":

            def distinct(s: Scope) -> list[Any]:
                keys: set[Any] = set()
                out: list[Any] = []
                for x in items(s):
                    k = json_key(x)
                    if k not in keys:
                        keys.add(k)
                        out.append(x)
                return out

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
            if not _is_number(v) or not isinstance(digits, int) or isinstance(digits, bool):
                raise EvaluationError("round: expects a number and a whole number of digits")
            # Half away from zero on the decimal value as written (2.675 -> 2.68, 2.5 -> 3),
            # as fees and credits are rounded; Python's round() is half-to-even on binary floats.
            try:
                exact = Decimal(repr(v)).quantize(Decimal(1).scaleb(-digits), ROUND_HALF_UP)
            except InvalidOperation as exc:
                raise EvaluationError(f"round: cannot round {v!r}") from exc
            return int(exact) if digits <= 0 else float(exact)

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
