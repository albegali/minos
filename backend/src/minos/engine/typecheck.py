"""Static checks of a rule graph against the entity schema and its own declarations.

Run at publish time. Each finding is an :class:`Issue`; publishing fails if any is found.

Checks:

* ``$.input`` references must resolve in the entity schema (typos, removed fields);
* ``$.item`` inside ``where`` / ``select`` resolves against the element schema of the array;
* ``$.vars.<name>`` must be a constant or assigned by a ``set`` node;
* ``$.nodes.<id>`` must name an existing node, ``$.meta.<key>`` a known metadata key;
* aggregate functions need an array source;
* ordering / equality comparisons between a field and a literal of an incompatible type
  (e.g. a string field compared with ``> 5``) are rejected, since they can never be true.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from minos.schema.paths import SchemaNode, resolve_path

from .errors import CompileError
from .model import ConditionNode, EndNode, FeedbackNode, GroupNode, RuleGraph, SetNode, SwitchNode
from .refs import parse_path
from .templates import PLACEHOLDER

META_KEYS: Final = frozenset({"ruleset", "version", "referenceDate", "requestId", "locale"})
_AGGREGATES: Final = frozenset(
    {"sum", "count", "min", "max", "avg", "any", "all", "distinct", "filter", "map"}
)
_NUMERIC_AGGREGATES: Final = frozenset({"sum", "min", "max", "avg"})
_ORDERING: Final = frozenset({"<", "<=", ">", ">="})


@dataclass(frozen=True, slots=True)
class Issue:
    where: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"where": self.where, "message": self.message}


class TypeCheckError(CompileError):
    """One or more static issues; ``issues`` lists all of them."""

    def __init__(self, issues: list[Issue]) -> None:
        self.issues = issues
        first = issues[0]
        more = f" (+{len(issues) - 1} more)" if len(issues) > 1 else ""
        super().__init__(first.message + more, first.where)


_UNKNOWN = object()  # "no schema information" for $.item outside a typed aggregate

type Ctx = tuple[SchemaNode | object | None, SchemaNode | object | None]
"""Schemas bound to ``$.item`` and ``$.outer`` (``None``: not inside an aggregate)."""
NO_ITEM: Ctx = (None, None)


class _Checker:
    def __init__(self, graph: RuleGraph, schema: dict[str, Any] | None) -> None:
        self.schema = schema
        self.node_ids = {n.id for n in graph.nodes}
        self.var_names = set(graph.constants)
        for n in graph.nodes:
            if isinstance(n, SetNode):
                self.var_names.update(n.assign)
        self.issues: list[Issue] = []

    def issue(self, where: str, message: str) -> None:
        self.issues.append(Issue(where, message))

    # ------------------------------------------------------------------ references

    def ref(self, path: Any, where: str, item: Ctx) -> SchemaNode | None:
        """Check a reference; return its schema node when known."""
        try:
            root, segments = parse_path(path)
        except CompileError as exc:
            self.issue(where, exc.message)
            return None
        if root == "input":
            if self.schema is None:
                return None
            node = resolve_path(self.schema, segments)
            if node is None:
                self.issue(where, f"{path} does not exist in the entity schema")
            return node
        if root in ("item", "outer"):
            scope = item[0] if root == "item" else item[1]
            if scope is None:
                where_ok = "'where' or 'select'" if root == "item" else "a nested aggregate"
                self.issue(where, f"$.{root} can only be used inside {where_ok}")
                return None
            if not isinstance(scope, SchemaNode):
                return None
            node = scope
            for seg in segments:
                sub = _step(node, seg)
                if sub is None:
                    self.issue(where, f"{path} does not exist in the array element schema")
                    return None
                node = sub
            return node
        if root == "vars":
            if segments and isinstance(segments[0], str) and segments[0] not in self.var_names:
                self.issue(where, f"variable {segments[0]!r} is neither a constant nor assigned")
        elif root == "nodes":
            if segments and isinstance(segments[0], str) and segments[0] not in self.node_ids:
                self.issue(where, f"node {segments[0]!r} does not exist")
        elif root == "meta" and segments and segments[0] not in META_KEYS:
            self.issue(where, f"unknown metadata key {segments[0]!r}")
        return None

    # ------------------------------------------------------------------ expressions

    def expr(self, e: Any, where: str, item: Ctx = NO_ITEM) -> None:
        if isinstance(e, list):
            for i, x in enumerate(e):
                self.expr(x, f"{where}[{i}]", item)
            return
        if not isinstance(e, dict):
            return
        if "ref" in e:
            self.ref(e["ref"], where, item)
        elif "fn" in e:
            self.fn(e, where, item)
        elif "op" in e:
            self.op(e, where, item)

    def fn(self, e: dict[str, Any], where: str, item: Ctx) -> None:
        name = e["fn"]
        args = e.get("args", [])
        if not isinstance(args, list):
            return
        if name not in _AGGREGATES or not args:
            self.expr(args, f"{where}.args", item)
            return
        source = args[0]
        element: SchemaNode | object = _UNKNOWN
        if isinstance(source, dict) and "ref" in source:
            node = self.ref(source["ref"], f"{where}.args[0]", item)
            if node is not None:
                if node.many:
                    element = SchemaNode(node.root, node.schemas, False)
                elif node.types is not None and "array" not in node.types:
                    self.issue(
                        f"{where}.args[0]",
                        f"{name}() needs an array, {source['ref']} is {_describe(node)}",
                    )
                else:
                    element = node.element() or _UNKNOWN
        else:
            self.expr(source, f"{where}.args[0]", item)
        self.expr(args[1:], f"{where}.args", item)
        inner: Ctx = (element, item[0])
        if "where" in e:
            self.expr(e["where"], f"{where}.where", inner)
        if "select" in e:
            self.expr(e["select"], f"{where}.select", inner)
        elif (
            name in _NUMERIC_AGGREGATES
            and isinstance(element, SchemaNode)
            and (types := element.types) is not None
            and not types & {"number", "null"}
        ):
            self.issue(where, f"{name}() needs numbers, the elements are {_describe(element)}")

    def op(self, e: dict[str, Any], where: str, item: Ctx) -> None:
        op = e["op"]
        operands = (
            e["args"]
            if isinstance(e.get("args"), list)
            else [e[k] for k in ("left", "right", "arg") if k in e]
        )
        known: list[SchemaNode | None] = []
        for i, operand in enumerate(operands):
            w = f"{where}.{['left', 'right'][i] if 'args' not in e and i < 2 else f'args[{i}]'}"
            if isinstance(operand, dict) and "ref" in operand:
                known.append(self.ref(operand["ref"], w, item))
            else:
                known.append(None)
                self.expr(operand, w, item)
        if len(operands) == 2 and (op in _ORDERING or op in ("==", "!=")):
            for field, literal in ((known[0], operands[1]), (known[1], operands[0])):
                if field is not None and not field.many:
                    self._literal_compat(op, field, literal, where)

    def _literal_compat(self, op: str, field: SchemaNode, literal: Any, where: str) -> None:
        types = field.types
        if types is None or isinstance(literal, (dict, list)) or literal is None:
            return
        lit = _json_type(literal)
        if lit in types or (lit == "number" and "integer" in types):
            return
        if op in ("==", "!="):
            self.issue(
                where,
                f"'{op}' compares {_describe(field)} with a {lit} literal: "
                "it is always " + ("false" if op == "==" else "true"),
            )
        else:
            self.issue(where, f"'{op}' compares {_describe(field)} with a {lit} literal")

    # ------------------------------------------------------------------ graph

    def graph(self, graph: RuleGraph) -> None:
        for name, value in graph.constants.items():
            self.expr(value, f"constants.{name}")
        for n in graph.nodes:
            w = f"nodes.{n.id}"
            match n:
                case ConditionNode():
                    self.expr(n.condition, f"{w}.condition")
                    self._feedback(n.feedback, w)
                case GroupNode():
                    for i, child in enumerate(n.children):
                        if isinstance(child, dict) and "rule" in child:
                            self.expr(child["rule"], f"{w}.children[{i}].rule")
                            self._raw_feedback(child.get("feedback"), f"{w}.children[{i}]")
                        else:
                            self.expr(child, f"{w}.children[{i}]")
                    self._feedback(n.feedback, w)
                case SetNode():
                    for k, v in n.assign.items():
                        self.expr(v, f"{w}.assign.{k}")
                case SwitchNode():
                    for c in n.cases:
                        self.expr(c.when, f"{w}.cases.{c.name}")
                case FeedbackNode():
                    self.expr(n.when, f"{w}.when")
                    self._spec_data(n.feedback.data, f"{w}.feedback", n.feedback.message)
                case EndNode():
                    for k, v in (n.output or {}).items():
                        self.expr(v, f"{w}.output.{k}")

    def _feedback(self, fb: Any, where: str) -> None:
        if fb is None:
            return
        for port, spec in (("pass", fb.pass_), ("fail", fb.fail)):
            if spec is not None:
                self._spec_data(spec.data, f"{where}.feedback.{port}", spec.message)

    def _raw_feedback(self, fb: Any, where: str) -> None:
        if isinstance(fb, dict):
            for port in ("pass", "fail"):
                spec = fb.get(port)
                if isinstance(spec, dict):
                    self._spec_data(
                        spec.get("data"), f"{where}.feedback.{port}", spec.get("message")
                    )

    def _spec_data(self, data: Any, where: str, message: Any = None) -> None:
        for k, v in (data or {}).items():
            self.expr(v, f"{where}.data.{k}")
        texts = message.items() if isinstance(message, dict) else [("", message)]
        for loc, text in texts:
            if isinstance(text, str):
                w = f"{where}.message" + (f".{loc}" if loc else "")
                for m in PLACEHOLDER.finditer(text):
                    self.ref("$." + m.group(1), w, NO_ITEM)


def _step(node: SchemaNode, seg: Any) -> SchemaNode | None:
    if isinstance(seg, str):
        return node.child(seg)
    if isinstance(seg, int):
        return node.element()
    return node.spread()


def _json_type(v: Any) -> str:
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)):
        return "number"
    return "string"


def _describe(node: SchemaNode) -> str:
    types = node.types
    if types is None:
        return "untyped"
    shown = sorted(types - {"integer"} if "integer" in types and "number" in types else types)
    return "a field of type " + "/".join(shown)


def typecheck(graph: RuleGraph, schema: dict[str, Any] | None) -> list[Issue]:
    """Return every static issue of ``graph`` (empty list when it is clean)."""
    checker = _Checker(graph, schema)
    checker.graph(graph)
    return checker.issues
