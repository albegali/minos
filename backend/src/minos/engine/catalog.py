"""Catalogue of node types, operators and functions, served to the editor.

Minos Studio builds its palette, its node forms and its condition builder from this
catalogue (``GET /v1/node-types``), so a node or operator added here appears in the editor
without frontend changes. Tests assert that the catalogue matches what the compiler accepts.
"""

from __future__ import annotations

from typing import Any, Final

from .model import ConditionNode, EndNode, FeedbackNode, GroupNode, SetNode, StartNode, SwitchNode

type Manifest = dict[str, Any]

_NODES: Final[list[tuple[type[Any], Manifest]]] = [
    (
        StartNode,
        {
            "type": "start",
            "category": "flow",
            "icon": "play",
            "label": {"it": "Inizio", "en": "Start"},
            "description": {
                "it": "Punto di ingresso del grafo (uno solo)",
                "en": "Entry point of the graph (exactly one)",
            },
            "ports": ["next"],
            "requiredPorts": ["next"],
            "unique": True,
        },
    ),
    (
        ConditionNode,
        {
            "type": "condition",
            "category": "logic",
            "icon": "branch",
            "label": {"it": "Condizione", "en": "Condition"},
            "description": {
                "it": "Verifica una condizione; passa o fallisce",
                "en": "Checks a condition; passes or fails",
            },
            "ports": ["pass", "fail"],
            "requiredPorts": ["pass"],
        },
    ),
    (
        GroupNode,
        {
            "type": "group",
            "category": "logic",
            "icon": "group",
            "label": {"it": "Gruppo di regole", "en": "Rule group"},
            "description": {
                "it": "Più regole combinate con AND, OR o NOT, con feedback per regola",
                "en": "Several rules combined with AND, OR or NOT, with feedback per rule",
            },
            "ports": ["pass", "fail"],
            "requiredPorts": ["pass"],
        },
    ),
    (
        SwitchNode,
        {
            "type": "switch",
            "category": "flow",
            "icon": "switch",
            "label": {"it": "Switch", "en": "Switch"},
            "description": {
                "it": "Sceglie un ramo: vince il primo caso vero, altrimenti default",
                "en": "Picks a branch: the first true case wins, otherwise default",
            },
            "ports": ["default"],
            "dynamicPorts": "cases",
            "requiredPorts": ["default"],
        },
    ),
    (
        SetNode,
        {
            "type": "set",
            "category": "data",
            "icon": "calculator",
            "label": {"it": "Calcolo", "en": "Compute"},
            "description": {
                "it": "Calcola variabili riusabili negli altri nodi ($.vars)",
                "en": "Computes variables reusable by other nodes ($.vars)",
            },
            "ports": ["next"],
            "requiredPorts": ["next"],
        },
    ),
    (
        FeedbackNode,
        {
            "type": "feedback",
            "category": "output",
            "icon": "comment",
            "label": {"it": "Messaggio", "en": "Message"},
            "description": {
                "it": "Emette un messaggio, opzionalmente solo se una condizione è vera",
                "en": "Emits a message, optionally only when a condition holds",
            },
            "ports": ["next"],
            "requiredPorts": ["next"],
        },
    ),
    (
        EndNode,
        {
            "type": "end",
            "category": "output",
            "icon": "flag",
            "label": {"it": "Fine", "en": "End"},
            "description": {
                "it": "Termina con un esito e un output",
                "en": "Ends with an outcome and an output",
            },
            "ports": [],
            "requiredPorts": [],
        },
    ),
]

CATEGORIES: Final = [
    {"key": "flow", "label": {"it": "Flusso", "en": "Flow"}},
    {"key": "logic", "label": {"it": "Logica", "en": "Logic"}},
    {"key": "data", "label": {"it": "Dati", "en": "Data"}},
    {"key": "output", "label": {"it": "Output", "en": "Output"}},
]

# kind: "compare" (left, right), "unary" (arg), "logic" (args), "range" (left, [low, high]),
# "arith" (args, >= 2), "if" (3 args). types: JSON types the left operand may have.
OPERATORS: Final[list[dict[str, Any]]] = [
    {"op": "==", "kind": "compare", "label": {"it": "è uguale a", "en": "equals"}},
    {"op": "!=", "kind": "compare", "label": {"it": "è diverso da", "en": "differs from"}},
    {
        "op": ">",
        "kind": "compare",
        "types": ["number", "string"],
        "label": {"it": "è maggiore di", "en": "is greater than"},
    },
    {
        "op": ">=",
        "kind": "compare",
        "types": ["number", "string"],
        "label": {"it": "è maggiore o uguale a", "en": "is at least"},
    },
    {
        "op": "<",
        "kind": "compare",
        "types": ["number", "string"],
        "label": {"it": "è minore di", "en": "is less than"},
    },
    {
        "op": "<=",
        "kind": "compare",
        "types": ["number", "string"],
        "label": {"it": "è minore o uguale a", "en": "is at most"},
    },
    {
        "op": "between",
        "kind": "range",
        "types": ["number", "string"],
        "label": {"it": "è compreso tra", "en": "is between"},
    },
    {
        "op": "in",
        "kind": "compare",
        "rightList": True,
        "label": {"it": "è uno tra", "en": "is one of"},
    },
    {
        "op": "not_in",
        "kind": "compare",
        "rightList": True,
        "label": {"it": "non è uno tra", "en": "is none of"},
    },
    {
        "op": "contains",
        "kind": "compare",
        "types": ["string", "array"],
        "label": {"it": "contiene", "en": "contains"},
    },
    {
        "op": "starts_with",
        "kind": "compare",
        "types": ["string"],
        "label": {"it": "inizia con", "en": "starts with"},
    },
    {
        "op": "ends_with",
        "kind": "compare",
        "types": ["string"],
        "label": {"it": "finisce con", "en": "ends with"},
    },
    {
        "op": "regex",
        "kind": "compare",
        "types": ["string"],
        "rightLiteral": True,
        "label": {"it": "rispetta il pattern", "en": "matches the pattern"},
    },
    {
        "op": "date_before",
        "kind": "compare",
        "types": ["string"],
        "formats": ["date", "date-time"],
        "label": {"it": "è prima del", "en": "is before"},
    },
    {
        "op": "date_after",
        "kind": "compare",
        "types": ["string"],
        "formats": ["date", "date-time"],
        "label": {"it": "è dopo il", "en": "is after"},
    },
    {
        "op": "date_between",
        "kind": "range",
        "types": ["string"],
        "formats": ["date", "date-time"],
        "label": {"it": "è una data tra", "en": "is a date between"},
    },
    {"op": "exists", "kind": "unary", "label": {"it": "è presente", "en": "is present"}},
    {"op": "is_null", "kind": "unary", "label": {"it": "è vuoto", "en": "is empty"}},
    {"op": "is_not_null", "kind": "unary", "label": {"it": "non è vuoto", "en": "is not empty"}},
    {"op": "and", "kind": "logic", "label": {"it": "tutte vere (AND)", "en": "all true (AND)"}},
    {"op": "or", "kind": "logic", "label": {"it": "almeno una vera (OR)", "en": "any true (OR)"}},
    {"op": "not", "kind": "unary", "label": {"it": "non (NOT)", "en": "not (NOT)"}},
    {
        "op": "if",
        "kind": "if",
        "label": {"it": "se … allora … altrimenti", "en": "if … then … else"},
    },
    {"op": "+", "kind": "arith", "label": {"it": "somma", "en": "plus"}},
    {"op": "-", "kind": "arith", "label": {"it": "meno", "en": "minus"}},
    {"op": "*", "kind": "arith", "label": {"it": "per", "en": "times"}},
    {"op": "/", "kind": "arith", "label": {"it": "diviso", "en": "divided by"}},
    {"op": "%", "kind": "arith", "label": {"it": "resto di", "en": "modulo"}},
]

# aggregate: first argument is an array, accepts where/select. returns: result JSON type.
FUNCTIONS: Final[list[dict[str, Any]]] = [
    {"fn": "sum", "aggregate": True, "returns": "number", "label": {"it": "somma", "en": "sum"}},
    {
        "fn": "count",
        "aggregate": True,
        "returns": "number",
        "label": {"it": "conteggio", "en": "count"},
    },
    {"fn": "min", "aggregate": True, "returns": "number", "label": {"it": "minimo", "en": "min"}},
    {"fn": "max", "aggregate": True, "returns": "number", "label": {"it": "massimo", "en": "max"}},
    {
        "fn": "avg",
        "aggregate": True,
        "returns": "number",
        "label": {"it": "media", "en": "average"},
    },
    {
        "fn": "any",
        "aggregate": True,
        "returns": "boolean",
        "label": {"it": "almeno un elemento", "en": "any element"},
    },
    {
        "fn": "all",
        "aggregate": True,
        "returns": "boolean",
        "label": {"it": "tutti gli elementi", "en": "every element"},
    },
    {
        "fn": "distinct",
        "aggregate": True,
        "returns": "array",
        "label": {"it": "valori distinti", "en": "distinct values"},
    },
    {
        "fn": "filter",
        "aggregate": True,
        "returns": "array",
        "label": {"it": "filtra", "en": "filter"},
    },
    {"fn": "map", "aggregate": True, "returns": "array", "label": {"it": "trasforma", "en": "map"}},
    {"fn": "len", "args": 1, "returns": "number", "label": {"it": "lunghezza", "en": "length"}},
    {
        "fn": "lower",
        "args": 1,
        "returns": "string",
        "label": {"it": "minuscolo", "en": "lower case"},
    },
    {
        "fn": "upper",
        "args": 1,
        "returns": "string",
        "label": {"it": "maiuscolo", "en": "upper case"},
    },
    {"fn": "trim", "args": 1, "returns": "string", "label": {"it": "senza spazi", "en": "trim"}},
    {
        "fn": "coalesce",
        "args": "1+",
        "returns": "any",
        "label": {"it": "primo valore presente", "en": "first present value"},
    },
    {
        "fn": "round",
        "args": "1-2",
        "returns": "number",
        "label": {"it": "arrotonda", "en": "round"},
    },
    {
        "fn": "abs",
        "args": 1,
        "returns": "number",
        "label": {"it": "valore assoluto", "en": "absolute value"},
    },
    {"fn": "floor", "args": 1, "returns": "number", "label": {"it": "parte intera", "en": "floor"}},
    {"fn": "date", "args": 1, "returns": "string", "label": {"it": "data", "en": "date"}},
    {
        "fn": "today",
        "args": 0,
        "returns": "string",
        "label": {"it": "data di riferimento", "en": "reference date"},
    },
    {
        "fn": "days_between",
        "args": 2,
        "returns": "number",
        "label": {"it": "giorni tra", "en": "days between"},
    },
    {"fn": "age", "args": "1-2", "returns": "number", "label": {"it": "età", "en": "age"}},
]


def node_types() -> list[Manifest]:
    """Manifests with the JSON Schema of each node's parameters."""
    out = []
    for model, manifest in _NODES:
        schema = model.model_json_schema(by_alias=True)
        props = {k: v for k, v in schema.get("properties", {}).items() if k not in ("id", "type")}
        params = {**schema, "properties": props}
        params["required"] = [r for r in schema.get("required", []) if r not in ("id", "type")]
        out.append({**manifest, "params": params})
    return out


def catalog() -> dict[str, Any]:
    return {
        "rgdVersion": "1.0",
        "categories": CATEGORIES,
        "nodeTypes": node_types(),
        "operators": OPERATORS,
        "functions": FUNCTIONS,
        "roots": ["input", "vars", "nodes", "meta", "item", "outer"],
        "metaKeys": ["ruleset", "version", "referenceDate", "requestId", "locale"],
    }
