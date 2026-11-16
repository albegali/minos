"""Compiler: Rule Graph Document (JSON) -> :class:`CompiledRuleset`.

Compilation validates the document (structure, ports, cycles, expressions) and turns
every node into a closure, so that executing a rule set does no parsing at all.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from .errors import CompileError
from .expressions import Evaluator, clean, compile_expr
from .model import (
    ConditionNode,
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
    SwitchNode,
)
from .refs import Scope
from .runtime import (
    FAIL,
    PASS,
    CompiledFeedback,
    CompiledNode,
    CompiledRuleset,
    ExecutionState,
    NodeFn,
    NodeOutcome,
)
from .templates import compile_template

NEXT = "next"
DEFAULT = "default"


def graph_hash(doc: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical JSON of ``doc`` without editor-only data (``ui``)."""
    payload = {k: v for k, v in doc.items() if k != "ui"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def compile_ruleset(doc: Mapping[str, Any] | RuleGraph) -> CompiledRuleset:
    """Validate and compile a rule graph document."""
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
    return _Compiler(graph, graph_hash(raw)).build()


class _Compiler:
    def __init__(self, graph: RuleGraph, digest: str) -> None:
        self.g = graph
        self.digest = digest
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
            case ConditionNode() | GroupNode():
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
            case ConditionNode() | GroupNode():
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


def _feedback_fn(nid: str, fb: CompiledFeedback | None, when: Evaluator | None) -> NodeFn:
    def run(scope: Scope, state: ExecutionState) -> tuple[NodeOutcome, str, Any]:
        if when is None or when(scope):
            state.emit(fb, scope, nid)
            return PASS, NEXT, True
        return PASS, NEXT, False

    return run
