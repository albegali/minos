"""Pydantic models of the Rule Graph Document (RGD) format, version 1.0.

These models are used only at compile time (publishing); the hot path works on
compiled closures and plain dicts. Field names follow the JSON format (camelCase).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

type Expr = Any
"""An expression AST, validated by :func:`minos.engine.expressions.compile_expr`."""

type Severity = Literal["info", "warning", "error"]
type OnFail = Literal["stop", "continue", "branch"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, frozen=True)


class FeedbackSpec(_Strict):
    code: str
    severity: Severity = "error"
    message: str | dict[str, str]
    """Plain text or a ``{locale: text}`` map; ``{{vars.x}}`` placeholders allowed."""
    path: str | None = None
    """Field of the input the message is about (for UIs), e.g. ``courses[2].cfu``."""
    data: dict[str, Expr] | None = None
    """Extra values (expressions) attached to the feedback, e.g. actual vs required."""


class NodeFeedback(_Strict):
    pass_: FeedbackSpec | None = Field(default=None, alias="pass")
    fail: FeedbackSpec | None = None


class Rule(_Strict):
    """A child of a group with its own feedback: ``{"rule": <expr>, "feedback": {...}}``."""

    rule: Expr
    feedback: NodeFeedback | None = None


class _Node(_Strict):
    id: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_\-]*$")
    label: str | None = None
    description: str | None = None


class StartNode(_Node):
    type: Literal["start"]


class ConditionNode(_Node):
    type: Literal["condition"]
    condition: Expr
    onFail: OnFail | None = None
    feedback: NodeFeedback | None = None


class GroupNode(_Node):
    type: Literal["group"]
    operator: Literal["and", "or", "not"]
    evaluate: Literal["short_circuit", "all"] = "short_circuit"
    children: list[Expr] = Field(min_length=1)
    onFail: OnFail | None = None
    feedback: NodeFeedback | None = None


class SetNode(_Node):
    type: Literal["set"]
    assign: dict[str, Expr] = Field(min_length=1)


class SwitchCase(_Strict):
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_\-]*$")
    when: Expr


class SwitchNode(_Node):
    type: Literal["switch"]
    cases: list[SwitchCase] = Field(min_length=1)


class FeedbackNode(_Node):
    type: Literal["feedback"]
    feedback: FeedbackSpec
    when: Expr | None = None


class EndNode(_Node):
    type: Literal["end"]
    outcome: Literal["valid", "invalid", "warning"]
    output: dict[str, Expr] | None = None


_IDENT = r"^[A-Za-z_][A-Za-z0-9_]*$"

type HitPolicy = Literal["first", "unique", "priority", "any", "collect"]


class DecisionColumn(_Strict):
    name: str = Field(pattern=_IDENT)
    label: str | None = None


class DecisionInput(DecisionColumn):
    expr: Expr
    """Value tested by the cells of this column, e.g. ``{"ref": "$.input.program.code"}``."""


class DecisionRule(_Strict):
    when: list[Any]
    """One cell per input: ``null`` (any), a value, a list (any of), or
    ``{"op": "<op>", "value": <value or expression>}``."""
    then: dict[str, Expr]
    """Output column -> value (literal or expression)."""
    priority: float = 0
    description: str | None = None


class DecisionTableNode(_Node):
    type: Literal["decision_table"]
    hitPolicy: HitPolicy = "first"
    inputs: list[DecisionInput] = Field(min_length=1)
    outputs: list[DecisionColumn] = Field(min_length=1)
    rules: list[DecisionRule] = Field(min_length=1)
    target: str = Field(pattern=_IDENT)
    """Variable receiving the result: an object, or a list of objects with ``collect``."""
    onFail: OnFail | None = None
    feedback: NodeFeedback | None = None


class SubRulesetNode(_Node):
    type: Literal["subruleset"]
    ruleset: str = Field(pattern=r"^[a-z0-9][a-z0-9_.\-]*$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    """Published version, pinned: the parent stays reproducible."""
    input: Expr = Field(default_factory=lambda: {"ref": "$.input"})
    forEach: Expr | None = None
    """When set, the rule set runs once per element (``$.item``); ``input`` defaults to it."""
    passWhen: Literal["all", "any"] = "all"
    """With ``forEach``: pass when every run, or at least one run, is valid."""
    target: str | None = Field(default=None, pattern=_IDENT)
    """Variable receiving the child result (a list of results with ``forEach``)."""
    onFail: OnFail | None = None
    feedback: NodeFeedback | None = None


type Node = Annotated[
    StartNode
    | ConditionNode
    | GroupNode
    | SetNode
    | SwitchNode
    | FeedbackNode
    | DecisionTableNode
    | SubRulesetNode
    | EndNode,
    Field(discriminator="type"),
]


class Edge(_Strict):
    from_: str = Field(alias="from")
    to: str
    on: str = "next"


class Settings(_Strict):
    mode: Literal["fail_fast", "collect_all"] = "fail_fast"
    locale: str = "it"
    maxSteps: int = Field(default=5000, ge=1)


class SchemaRef(_Strict):
    entity: str
    version: int


class RuleGraph(_Strict):
    rgdVersion: Literal["1.0"]
    ruleset: str = Field(pattern=r"^[a-z0-9][a-z0-9_.\-]*$")
    version: str = "0.0.0"
    schemaRef: SchemaRef | None = None
    settings: Settings = Settings()
    constants: dict[str, Any] = Field(default_factory=dict)
    """Values copied into ``$.vars`` at the start of every execution."""
    nodes: list[Node] = Field(min_length=2)
    edges: list[Edge]
    ui: dict[str, Any] | None = None
    """Editor-only data (positions, notes); excluded from the version hash."""
