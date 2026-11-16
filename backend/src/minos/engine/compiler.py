"""Compiler: Rule Graph Document (JSON) -> :class:`CompiledRuleset`.

Compilation validates the document (structure, ports, cycles, expressions) and turns
every node into a closure, so that executing a rule set does no parsing at all.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from typing import Any

from pydantic import ValidationError

from .decision import DecisionTable, compile_table
from .errors import CompileError, EvaluationError
from .expressions import Evaluator, clean, compile_expr
from .model import (
    ConditionNode,
    DecisionTableNode,
    EndNode,
    FeedbackNode,
    FeedbackSpec,
    GroupNode,
    Node,
    NodeFeedback,
    Rule,
    RuleGraph,
    SetNode,
    StartNode,
    SubRulesetNode,
    SwitchNode,
)
from .refs import MISSING, Scope
from .runtime import (
    FAIL,
    PASS,
    CompiledFeedback,
    CompiledNode,
    CompiledRuleset,
    ExecuteOptions,
    ExecutionState,
    NodeFn,
    NodeOutcome,
)
from .templates import compile_template
from .typecheck import TypeCheckError, typecheck

NEXT = "next"
DEFAULT = "default"


def graph_hash(doc: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical JSON of ``doc`` without editor-only data (``ui``)."""
    payload = {k: v for k, v in doc.items() if k != "ui"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


type Resolver = Callable[[str, str], CompiledRuleset]
"""``(ruleset key, version) -> compiled rule set``, for sub-ruleset nodes."""


def dependencies(doc: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Sub-rulesets referenced by a graph document, as ``(key, version)`` pairs."""
    out = []
    for node in doc.get("nodes", []) or []:
        if isinstance(node, dict) and node.get("type") == "subruleset":
            key, version = node.get("ruleset"), node.get("version")
            if isinstance(key, str) and isinstance(version, str):
                out.append((key, version))
    return out


def compile_ruleset(
    doc: Mapping[str, Any] | RuleGraph,
    schema: Mapping[str, Any] | None = None,
    resolve: Resolver | None = None,
) -> CompiledRuleset:
    """Validate, type-check and compile a rule graph document.

    ``schema`` is the entity JSON Schema; when given, ``$.input`` references are checked
    against it. ``resolve`` supplies the compiled rule sets used by sub-ruleset nodes.
    Static issues raise :class:`~minos.engine.typecheck.TypeCheckError`.
    """
    if isinstance(doc, RuleGraph):
        graph = doc
        raw = doc.model_dump(mode="json", by_alias=True, exclude_none=True)
    else:
        raw = dict(doc)
        try:
            graph = RuleGraph.model_validate(raw)
        except ValidationError as exc:
            first = exc.errors()[0]
            loc = ".".join(str(p) for p in first["loc"])
            raise CompileError(
                f"{first['msg']} ({exc.error_count()} error(s))", loc or None
            ) from exc
    compiled = _Compiler(graph, graph_hash(raw), resolve).build()
    issues = typecheck(graph, dict(schema) if schema is not None else None)
    if issues:
        raise TypeCheckError(issues)
    return compiled


class _Compiler:
    def __init__(self, graph: RuleGraph, digest: str, resolve: Resolver | None = None) -> None:
        self.g = graph
        self.digest = digest
        self.resolve = resolve
        self.locale = graph.settings.locale

    # ------------------------------------------------------------------ structure

    def build(self) -> CompiledRuleset:
        g = self.g
        by_id: dict[str, Node] = {}
        for n in g.nodes:
            if n.id in by_id:
                raise CompileError(f"duplicate node id {n.id!r}", "nodes")
            by_id[n.id] = n

        starts = [n for n in g.nodes if isinstance(n, StartNode)]
        if len(starts) != 1:
            raise CompileError(f"exactly one start node required, found {len(starts)}", "nodes")
        if not any(isinstance(n, EndNode) for n in g.nodes):
            raise CompileError("at least one end node required", "nodes")

        out: dict[str, dict[str, str]] = {nid: {} for nid in by_id}
        for i, e in enumerate(g.edges):
            where = f"edges[{i}]"
            if e.from_ not in by_id:
                raise CompileError(f"unknown source node {e.from_!r}", where)
            if e.to not in by_id:
                raise CompileError(f"unknown target node {e.to!r}", where)
            if isinstance(by_id[e.to], StartNode):
                raise CompileError("edges cannot point to the start node", where)
            allowed = self._ports(by_id[e.from_])
            if e.on not in allowed:
                raise CompileError(
                    f"node {e.from_!r} has no port {e.on!r} (allowed: {sorted(allowed)})", where
                )
            if e.on in out[e.from_]:
                raise CompileError(f"port {e.on!r} of {e.from_!r} is connected twice", where)
            out[e.from_][e.on] = e.to

        for nid, node in by_id.items():
            missing = self._required_ports(node) - out[nid].keys()
            if missing:
                raise CompileError(f"unconnected port(s) {sorted(missing)}", f"nodes.{nid}")

        self._check_acyclic(starts[0].id, out)
        reachable = self._reachable(starts[0].id, out)
        warnings = tuple(
            f"node {nid!r} is unreachable from start" for nid in by_id if nid not in reachable
        )

        compiled: dict[str, CompiledNode] = {}
        for nid, node in by_id.items():
            compiled[nid] = self._compile_node(node, out[nid])
        for nid, ports in out.items():
            compiled[nid].edges = {port: compiled[target] for port, target in ports.items()}

        return CompiledRuleset(
            ruleset=g.ruleset,
            version=g.version,
            hash=self.digest,
            mode=g.settings.mode,
            locale=self.locale,
            max_steps=g.settings.maxSteps,
            constants=dict(g.constants),
            start=compiled[starts[0].id],
            nodes=compiled,
            warnings=warnings,
        )

    @staticmethod
    def _ports(node: Node) -> set[str]:
        match node:
            case ConditionNode() | GroupNode() | DecisionTableNode() | SubRulesetNode():
                return {PASS, FAIL}
            case SwitchNode():
                return {c.name for c in node.cases} | {DEFAULT}
            case EndNode():
                return set()
            case _:
                return {NEXT}

    @staticmethod
    def _required_ports(node: Node) -> set[str]:
        match node:
            case ConditionNode() | GroupNode() | DecisionTableNode() | SubRulesetNode():
                return {PASS}
            case SwitchNode():
                return {c.name for c in node.cases} | {DEFAULT}
            case EndNode():
                return set()
            case _:
                return {NEXT}

    @staticmethod
    def _check_acyclic(start: str, out: dict[str, dict[str, str]]) -> None:
        white, grey, black = 0, 1, 2
        color = dict.fromkeys(out, white)
        for root in [start, *out]:
            if color[root] != white:
                continue
            stack: list[tuple[str, list[str]]] = [(root, list(out[root].values()))]
            color[root] = grey
            while stack:
                nid, pending = stack[-1]
                if not pending:
                    color[nid] = black
                    stack.pop()
                    continue
                nxt = pending.pop()
                if color[nxt] == grey:
                    raise CompileError(f"cycle detected through {nid!r} -> {nxt!r}", "edges")
                if color[nxt] == white:
                    color[nxt] = grey
                    stack.append((nxt, list(out[nxt].values())))

    @staticmethod
    def _reachable(start: str, out: dict[str, dict[str, str]]) -> set[str]:
        seen = {start}
        todo = [start]
        while todo:
            for nxt in out[todo.pop()].values():
                if nxt not in seen:
                    seen.add(nxt)
                    todo.append(nxt)
        return seen

    # ------------------------------------------------------------------ nodes

    def _on_fail(self, policy: str | None, ports: dict[str, str], where: str) -> str:
        if policy == "branch" and FAIL not in ports:
            raise CompileError("onFail 'branch' requires a connected 'fail' port", where)
        if policy is not None:
            return policy
        if FAIL in ports:
            return "branch"
        return "stop" if self.g.settings.mode == "fail_fast" else "continue"

    def _feedback(self, spec: FeedbackSpec | None, where: str) -> CompiledFeedback | None:
        if spec is None:
            return None
        messages = spec.message if isinstance(spec.message, dict) else {self.locale: spec.message}
        if not messages:
            raise CompileError("feedback message cannot be empty", where)
        return CompiledFeedback(
            code=spec.code,
            severity=spec.severity,
            messages={
                loc: compile_template(text, f"{where}.message.{loc}")
                for loc, text in messages.items()
            },
            default_locale=self.locale,
            path=spec.path,
            data=tuple(
                (k, compile_expr(v, f"{where}.data.{k}")) for k, v in (spec.data or {}).items()
            ),
        )

    def _pair(
        self, fb: NodeFeedback | None, where: str
    ) -> tuple[CompiledFeedback | None, CompiledFeedback | None]:
        if fb is None:
            return None, None
        return (
            self._feedback(fb.pass_, f"{where}.feedback.pass"),
            self._feedback(fb.fail, f"{where}.feedback.fail"),
        )

    def _compile_node(self, node: Node, ports: dict[str, str]) -> CompiledNode:
        where = f"nodes.{node.id}"
        nid = node.id
        match node:
            case StartNode():
                return CompiledNode(nid, "start", _passthrough, "stop")
            case EndNode():
                output = tuple(
                    (k, compile_expr(v, f"{where}.output.{k}"))
                    for k, v in (node.output or {}).items()
                )
                return CompiledNode(
                    nid, "end", _passthrough, "stop", end_outcome=node.outcome, end_output=output
                )
            case ConditionNode():
                cond = compile_expr(node.condition, f"{where}.condition")
                fb_pass, fb_fail = self._pair(node.feedback, where)
                return CompiledNode(
                    nid,
                    "condition",
                    _condition_fn(nid, cond, fb_pass, fb_fail),
                    self._on_fail(node.onFail, ports, where),
                )
            case GroupNode():
                return CompiledNode(
                    nid,
                    "group",
                    self._group_fn(node, where),
                    self._on_fail(node.onFail, ports, where),
                )
            case SetNode():
                assigns = tuple(
                    (k, compile_expr(v, f"{where}.assign.{k}")) for k, v in node.assign.items()
                )
                return CompiledNode(nid, "set", _set_fn(assigns), "stop")
            case SwitchNode():
                cases = tuple(
                    (c.name, compile_expr(c.when, f"{where}.cases.{c.name}")) for c in node.cases
                )
                return CompiledNode(nid, "switch", _switch_fn(cases), "stop")
            case FeedbackNode():
                fb = self._feedback(node.feedback, f"{where}.feedback")
                when = compile_expr(node.when, f"{where}.when") if node.when is not None else None
                return CompiledNode(nid, "feedback", _feedback_fn(nid, fb, when), "stop")
            case DecisionTableNode():
                table = compile_table(
                    node.hitPolicy,
                    [i.expr for i in node.inputs],
                    [o.name for o in node.outputs],
                    list(node.rules),
                    where,
                )
                fb_pass, fb_fail = self._pair(node.feedback, where)
                return CompiledNode(
                    nid,
                    "decision_table",
                    _decision_fn(nid, table, node.target, fb_pass, fb_fail),
                    self._on_fail(node.onFail, ports, where),
                )
            case SubRulesetNode():
                if self.resolve is None:
                    raise CompileError(
                        f"sub-ruleset {node.ruleset}@{node.version} cannot be resolved here", where
                    )
                try:
                    child = self.resolve(node.ruleset, node.version)
                except CompileError as exc:
                    raise CompileError(
                        f"sub-ruleset {node.ruleset}@{node.version}: {exc}", where
                    ) from exc
                fb_pass, fb_fail = self._pair(node.feedback, where)
                for_each = (
                    compile_expr(node.forEach, f"{where}.forEach")
                    if node.forEach is not None
                    else None
                )
                default_input = {"ref": "$.item"} if for_each is not None else {"ref": "$.input"}
                raw_input = node.input if "input" in node.model_fields_set else default_input
                return CompiledNode(
                    nid,
                    "subruleset",
                    _subruleset_fn(
                        nid,
                        child,
                        compile_expr(raw_input, f"{where}.input"),
                        for_each,
                        node.passWhen,
                        node.target,
                        fb_pass,
                        fb_fail,
                    ),
                    self._on_fail(node.onFail, ports, where),
                )
        raise CompileError(f"unsupported node type {node.type!r}", where)  # pragma: no cover

    def _group_fn(self, node: GroupNode, where: str) -> NodeFn:
        children: list[tuple[Evaluator, CompiledFeedback | None, CompiledFeedback | None]] = []
        for i, child in enumerate(node.children):
            cw = f"{where}.children[{i}]"
            if isinstance(child, dict) and "rule" in child:
                rule = Rule.model_validate(child)
                fp, ff = self._pair(rule.feedback, cw)
                children.append((compile_expr(rule.rule, f"{cw}.rule"), fp, ff))
            else:
                children.append((compile_expr(child, cw), None, None))
        frozen = tuple(children)
        fb_pass, fb_fail = self._pair(node.feedback, where)
        op = node.operator
        evaluate_all = node.evaluate == "all"
        nid = node.id

        def run(scope: Scope, state: ExecutionState) -> tuple[NodeOutcome, str, Any]:
            results: list[bool] = []
            for ev, cp, cf in frozen:
                ok = bool(ev(scope))
                results.append(ok)
                state.emit(cp if ok else cf, scope, nid)
                if not evaluate_all and ((op == "or" and ok) or (op != "or" and not ok)):
                    break
            if op == "or":
                passed = any(results)
            elif op == "and":
                passed = all(results) and len(results) == len(frozen)
            else:  # not: NOT(AND(children))
                passed = not (all(results) and len(results) == len(frozen))
            state.emit(fb_pass if passed else fb_fail, scope, nid)
            return (PASS, PASS, results) if passed else (FAIL, FAIL, results)

        return run


# ---------------------------------------------------------------------- node closures


def _passthrough(scope: Scope, state: ExecutionState) -> tuple[NodeOutcome, str, Any]:
    return PASS, NEXT, None


def _condition_fn(
    nid: str, cond: Evaluator, fb_pass: CompiledFeedback | None, fb_fail: CompiledFeedback | None
) -> NodeFn:
    def run(scope: Scope, state: ExecutionState) -> tuple[NodeOutcome, str, Any]:
        if cond(scope):
            state.emit(fb_pass, scope, nid)
            return PASS, PASS, True
        state.emit(fb_fail, scope, nid)
        return FAIL, FAIL, False

    return run


def _set_fn(assigns: tuple[tuple[str, Evaluator], ...]) -> NodeFn:
    def run(scope: Scope, state: ExecutionState) -> tuple[NodeOutcome, str, Any]:
        variables = scope["vars"]
        written = {}
        for key, ev in assigns:
            written[key] = variables[key] = clean(ev(scope))
        return PASS, NEXT, written

    return run


def _switch_fn(cases: tuple[tuple[str, Evaluator], ...]) -> NodeFn:
    def run(scope: Scope, state: ExecutionState) -> tuple[NodeOutcome, str, Any]:
        for name, when in cases:
            if when(scope):
                return PASS, name, name
        return PASS, DEFAULT, DEFAULT

    return run


def _decision_fn(
    nid: str,
    table: DecisionTable,
    target: str,
    fb_pass: CompiledFeedback | None,
    fb_fail: CompiledFeedback | None,
) -> NodeFn:
    def run(scope: Scope, state: ExecutionState) -> tuple[NodeOutcome, str, Any]:
        rows, result = table.evaluate(scope)
        scope["vars"][target] = result
        output = {"rows": [r + 1 for r in rows], "result": result}
        if rows:
            state.emit(fb_pass, scope, nid)
            return PASS, PASS, output
        state.emit(fb_fail, scope, nid)
        return FAIL, FAIL, output

    return run


def _subruleset_fn(
    nid: str,
    child: CompiledRuleset,
    input_: Evaluator,
    for_each: Evaluator | None,
    pass_when: str,
    target: str | None,
    fb_pass: CompiledFeedback | None,
    fb_fail: CompiledFeedback | None,
) -> NodeFn:
    label = f"{child.ruleset}@{child.version}"

    def call(scope: Scope, data: Any, index: int | None, state: ExecutionState) -> dict[str, Any]:
        meta = scope["meta"]
        result = child.execute(
            data,
            ExecuteOptions(
                locale=state.locale,
                reference_date=meta["referenceDate"],
                request_id=meta["requestId"],
            ),
        )
        if result["outcome"] == "error":
            where = f" (element {index})" if index is not None else ""
            messages = "; ".join(f["message"] for f in result["feedback"])
            raise EvaluationError(f"sub-ruleset {label}{where} failed: {messages}")
        for fb in result["feedback"]:
            copied = {**fb, "nodeId": f"{nid}/{fb['nodeId']}"}
            if index is not None:
                copied["index"] = index
            state.feedback.append(copied)
        return {"outcome": result["outcome"], "result": result["result"]}

    def run(scope: Scope, state: ExecutionState) -> tuple[NodeOutcome, str, Any]:
        if for_each is None:
            single = call(scope, input_(scope), None, state)
            passed = single["outcome"] in ("valid", "warning")
            output: Any = single
        else:
            items = for_each(scope)
            if items is None or items is MISSING:
                items = []
            if not isinstance(items, list):
                raise EvaluationError(f"sub-ruleset {label}: forEach needs a list")
            previous = scope.get("item", MISSING)
            runs = []
            try:
                for i, item in enumerate(items):
                    scope["item"] = item
                    runs.append(call(scope, input_(scope), i, state))
            finally:
                if previous is MISSING:
                    scope.pop("item", None)
                else:
                    scope["item"] = previous
            oks = [r["outcome"] in ("valid", "warning") for r in runs]
            passed = all(oks) if pass_when == "all" else any(oks)
            output = runs
        if target is not None:
            scope["vars"][target] = output
        state.emit(fb_pass if passed else fb_fail, scope, nid)
        return (PASS, PASS, output) if passed else (FAIL, FAIL, output)

    return run


def _feedback_fn(nid: str, fb: CompiledFeedback | None, when: Evaluator | None) -> NodeFn:
    def run(scope: Scope, state: ExecutionState) -> tuple[NodeOutcome, str, Any]:
        if when is None or when(scope):
            state.emit(fb, scope, nid)
            return PASS, NEXT, True
        return PASS, NEXT, False

    return run
