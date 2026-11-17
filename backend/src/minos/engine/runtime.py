"""Execution of compiled rule sets.

The runtime walks the graph from the start node following one outgoing edge per node
(the graph is a DAG, checked at compile time). Every node returns an outcome and the
port to follow; the runtime applies the ``onFail`` policy, collects feedback and stops
at an ``end`` node, at a failing node whose policy is ``stop``, or on an error.
"""

from __future__ import annotations

import datetime as dt
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from .errors import EvaluationError, ExecutionLimitError
from .expressions import Evaluator, clean
from .refs import Scope
from .templates import Renderer

type TraceLevel = Literal["none", "summary", "full"]
type NodeOutcome = Literal["pass", "fail"]

PASS: Final = "pass"
FAIL: Final = "fail"


@dataclass(slots=True, frozen=True)
class CompiledFeedback:
    code: str
    severity: str
    messages: Mapping[str, Renderer]
    default_locale: str
    path: str | None
    data: tuple[tuple[str, Evaluator], ...]

    def render(self, scope: Scope, node_id: str, locale: str) -> dict[str, Any]:
        renderer = (
            self.messages.get(locale)
            or self.messages.get(self.default_locale)
            or next(iter(self.messages.values()))
        )
        fb: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "message": renderer(scope),
            "nodeId": node_id,
        }
        if self.path is not None:
            fb["path"] = self.path
        if self.data:
            fb["data"] = {k: clean(ev(scope)) for k, ev in self.data}
        return fb


@dataclass(slots=True)
class ExecutionState:
    """Mutable per-execution state handed to node functions."""

    locale: str
    feedback: list[dict[str, Any]] = field(default_factory=list)

    def emit(self, fb: CompiledFeedback | None, scope: Scope, node_id: str) -> None:
        if fb is not None:
            self.feedback.append(fb.render(scope, node_id, self.locale))


type NodeFn = Callable[[Scope, ExecutionState], tuple[NodeOutcome, str, Any]]
"""``(scope, state) -> (outcome, port, output)``."""


@dataclass(slots=True, eq=False)
class CompiledNode:
    id: str
    type: str
    run: NodeFn
    on_fail: str
    edges: dict[str, CompiledNode] = field(default_factory=dict)
    end_outcome: str | None = None
    end_output: tuple[tuple[str, Evaluator], ...] = ()


@dataclass(slots=True, frozen=True)
class ExecuteOptions:
    trace: TraceLevel = "none"
    locale: str | None = None
    reference_date: str | None = None
    request_id: str | None = None


@dataclass(slots=True)
class CompiledRuleset:
    ruleset: str
    version: str
    hash: str
    mode: str
    locale: str
    max_steps: int
    constants: Mapping[str, Any]
    start: CompiledNode
    nodes: Mapping[str, CompiledNode]
    warnings: tuple[str, ...] = ()

    def execute(self, data: Any, options: ExecuteOptions | None = None) -> dict[str, Any]:
        """Evaluate ``data`` and return the JSON-serialisable result document."""
        opts = options or ExecuteOptions()
        t0 = time.perf_counter_ns()
        locale = opts.locale or self.locale
        request_id = opts.request_id or uuid.uuid4().hex
        reference_date = opts.reference_date or dt.datetime.now(dt.UTC).date().isoformat()

        node_slots: dict[str, Any] = {}
        scope: Scope = {
            "input": data,
            "vars": dict(self.constants),
            "nodes": node_slots,
            "meta": {
                "ruleset": self.ruleset,
                "version": self.version,
                "referenceDate": reference_date,
                "requestId": request_id,
                "locale": locale,
            },
        }
        state = ExecutionState(locale=locale)
        path: list[str] = []
        trace: list[dict[str, Any]] = []
        full = opts.trace == "full"
        traced = opts.trace != "none"
        failures: list[str] = []
        result: dict[str, Any] = {}

        node = self.start
        steps = 0
        while True:
            steps += 1
            if steps > self.max_steps:
                raise ExecutionLimitError(f"exceeded maxSteps={self.max_steps}")
            path.append(node.id)

            n0 = time.perf_counter_ns() if full else 0
            try:
                if node.type == "end":
                    for key, ev in node.end_output:
                        result[key] = clean(ev(scope))
                else:
                    node_outcome, port, output = node.run(scope, state)
            except _EVALUATION_FAILURES as exc:
                state.feedback.append(
                    {
                        "code": "MINOS_EVALUATION_ERROR",
                        "severity": "error",
                        "message": _failure_message(exc),
                        "nodeId": node.id,
                    }
                )
                if traced:
                    trace.append({"nodeId": node.id, "type": node.type, "outcome": "error"})
                outcome = "error"
                exit_info = {"nodeId": node.id, "reason": "error"}
                break

            if node.type == "end":
                outcome = _final_outcome(node.end_outcome or "valid", failures, state.feedback)
                exit_info = {"nodeId": node.id, "reason": "end"}
                if traced:
                    trace.append({"nodeId": node.id, "type": "end", "outcome": outcome})
                break

            node_slots[node.id] = {"outcome": node_outcome, "output": output}
            if traced:
                entry: dict[str, Any] = {
                    "nodeId": node.id,
                    "type": node.type,
                    "outcome": node_outcome,
                    "port": port,
                }
                if full:
                    entry["output"] = output
                    entry["us"] = (time.perf_counter_ns() - n0) / 1000
                trace.append(entry)

            if node_outcome == FAIL:
                if node.on_fail == "stop":
                    failures.append(node.id)
                    outcome = "invalid"
                    exit_info = {"nodeId": node.id, "reason": "stop"}
                    break
                if node.on_fail == "continue":
                    failures.append(node.id)
                nxt = node.edges.get(FAIL) or node.edges[PASS]
            else:
                nxt = node.edges[port]
            node = nxt

        return {
            "requestId": request_id,
            "ruleset": self.ruleset,
            "version": self.version,
            "outcome": outcome,
            "exit": exit_info,
            "feedback": state.feedback,
            "result": result,
            "path": path,
            "trace": trace if traced else None,
            "timing": {"engineUs": round((time.perf_counter_ns() - t0) / 1000, 1)},
        }


# Errors that values in the input can trigger while evaluating (types the schema did not rule
# out, overflows, malformed strings): reported as outcome ``error``, never as a crash.
_EVALUATION_FAILURES = (
    EvaluationError,
    ArithmeticError,
    TypeError,
    ValueError,
    LookupError,
    RecursionError,
)


MAX_MESSAGE = 300  # error messages quote values from the input: keep them short


def _failure_message(exc: BaseException) -> str:
    text = str(exc)
    if not isinstance(exc, EvaluationError):
        text = f"evaluation failed ({type(exc).__name__}): {text}"
    return text if len(text) <= MAX_MESSAGE else text[: MAX_MESSAGE - 1] + "…"


def _final_outcome(end_outcome: str, failures: list[str], feedback: list[dict[str, Any]]) -> str:
    """An ``end`` node declared ``valid`` is downgraded by recorded failures or feedback."""
    if end_outcome != "valid":
        return end_outcome
    if failures or any(f["severity"] == "error" for f in feedback):
        return "invalid"
    if any(f["severity"] == "warning" for f in feedback):
        return "warning"
    return "valid"
