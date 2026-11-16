"""Resolution of reference paths (``a.b[*].c``) against a JSON Schema.

Used by the compiler's type-check: a reference to a field the schema cannot contain is a
publish-time error instead of a silent ``false`` at runtime.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

type Segment = str | int | object

_ANY: dict[str, Any] = {}
# Keywords that describe the shape of a value; a sub-schema without any of them (e.g. an allOf
# member holding only "required") is a pure constraint and does not widen the candidates.
_SHAPING_KEYS = frozenset(
    {
        "type",
        "properties",
        "items",
        "prefixItems",
        "additionalProperties",
        "patternProperties",
        "$ref",
        "anyOf",
        "oneOf",
        "allOf",
        "enum",
        "const",
    }
)


@dataclass(frozen=True, slots=True)
class SchemaNode:
    """The set of sub-schemas a value at some path may match.

    ``schemas`` holds the candidates (an empty dict means "anything"); ``many`` is true when the
    path went through a ``[*]`` wildcard, so the runtime value is a list of such values.
    """

    root: dict[str, Any]
    schemas: tuple[dict[str, Any], ...]
    many: bool = False

    @property
    def types(self) -> frozenset[str] | None:
        """Possible JSON types, or ``None`` when unconstrained."""
        found: set[str] = set()
        for s in self.schemas:
            t = s.get("type")
            if t is None:
                if "properties" in s:
                    found.add("object")
                elif "items" in s:
                    found.add("array")
                else:
                    return None
            elif isinstance(t, list):
                found.update(t)
            else:
                found.add(t)
        if "integer" in found:
            found.add("number")
        return frozenset(found)

    @property
    def formats(self) -> frozenset[str]:
        return frozenset(f for s in self.schemas if isinstance(f := s.get("format"), str))

    def child(self, key: str) -> SchemaNode | None:
        out: list[dict[str, Any]] = []
        for s in self.schemas:
            if not _may_be(s, "object"):
                continue
            props = s.get("properties", {})
            if key in props:
                out.append(props[key])
                continue
            matched = False
            for pattern, sub in s.get("patternProperties", {}).items():
                if re.search(pattern, key):
                    out.append(sub)
                    matched = True
            if matched:
                continue
            # Undeclared keys count as absent when the object declares its properties, unless
            # additionalProperties says otherwise: this is what catches typos in rule paths.
            declared = "properties" in s or "patternProperties" in s
            extra = s.get("additionalProperties", not declared)
            if extra is True:
                out.append(_ANY)
            elif isinstance(extra, dict):
                out.append(extra)
        return self._make(out)

    def element(self) -> SchemaNode | None:
        out: list[dict[str, Any]] = []
        for s in self.schemas:
            if not _may_be(s, "array"):
                continue
            items = s.get("items", True)
            if items is True:
                out.append(_ANY)
            elif isinstance(items, dict):
                out.append(items)
            out.extend(s.get("prefixItems", []))
        return self._make(out)

    def _make(self, schemas: list[dict[str, Any]], many: bool | None = None) -> SchemaNode | None:
        expanded = _expand(self.root, schemas)
        if not expanded:
            return None
        return SchemaNode(self.root, tuple(expanded), self.many if many is None else many)

    def spread(self) -> SchemaNode | None:
        """``[*]``: the elements, flagged as many."""
        el = self.element()
        return None if el is None else SchemaNode(self.root, el.schemas, True)


def _may_be(schema: dict[str, Any], kind: str) -> bool:
    t = schema.get("type")
    if t is None:
        return True
    return kind in t if isinstance(t, list) else t == kind


def _deref(root: dict[str, Any], ref: str) -> dict[str, Any] | None:
    if not ref.startswith("#"):
        return _ANY  # external references are not resolved: treat as unconstrained
    node: Any = root
    for raw in ref.lstrip("#").split("/")[1:]:
        part = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, dict) else None


def _expand(root: dict[str, Any], schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Follow local ``$ref`` and flatten ``anyOf`` / ``oneOf`` / ``allOf`` into candidates."""
    out: list[dict[str, Any]] = []
    stack = list(schemas)
    seen = 0
    while stack and seen < 256:
        seen += 1
        s = stack.pop(0)
        if "$ref" in s:
            target = _deref(root, s["$ref"])
            if target is not None:
                stack.append(target)
            continue
        combos = [
            c
            for k in ("anyOf", "oneOf", "allOf")
            for c in s.get(k, [])
            if isinstance(c, dict) and _SHAPING_KEYS & c.keys()
        ]
        if combos:
            stack.extend(combos)
            rest = {k: v for k, v in s.items() if k not in ("anyOf", "oneOf", "allOf")}
            if any(k in rest for k in ("type", "properties", "items")):
                out.append(rest)
            continue
        out.append(s)
    return out


def resolve_path(schema: dict[str, Any], segments: tuple[Segment, ...]) -> SchemaNode | None:
    """Resolve ``segments`` (as produced by :func:`minos.engine.refs.parse_path`, without the
    root) against ``schema``. Returns ``None`` if no value can exist at that path."""
    node: SchemaNode | None = SchemaNode(schema, tuple(_expand(schema, [schema])) or (_ANY,))
    for seg in segments:
        if node is None:
            return None
        if isinstance(seg, str):
            node = node.child(seg)
        elif isinstance(seg, int):
            node = node.element()
        else:  # the [*] wildcard sentinel
            node = node.spread()
    return node
