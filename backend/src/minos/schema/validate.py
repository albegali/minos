"""Validation of JSON Schemas and of input objects against them (jsonschema-rs, Rust core)."""

from __future__ import annotations

from typing import Any

import jsonschema_rs

from .infer import SCHEMA_DIALECT


class SchemaError(ValueError):
    """The document is not a valid JSON Schema."""


def check_schema(schema: Any) -> None:
    """Raise :class:`SchemaError` unless ``schema`` is a valid draft 2020-12 schema object."""
    if not isinstance(schema, dict):
        raise SchemaError("a schema must be a JSON object")
    dialect = schema.get("$schema", SCHEMA_DIALECT)
    if dialect != SCHEMA_DIALECT:
        raise SchemaError(f"only JSON Schema draft 2020-12 is supported, got {dialect!r}")
    try:
        jsonschema_rs.meta.validate(schema)
    except jsonschema_rs.ValidationError as exc:
        raise SchemaError(exc.message) from exc
    for ref in _references(schema):
        if not ref.startswith(("#", "entity:")):
            raise SchemaError(
                f"$ref {ref!r} is not allowed: use local references (#/$defs/...) "
                "or other entities (entity:Key)"
            )


_REF_KEYWORDS = ("$ref", "$dynamicRef")


def _references(node: Any) -> list[str]:
    """Every ``$ref``/``$dynamicRef`` value in ``node`` (data keywords included: harmless)."""
    out: list[str] = []
    stack = [node]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                if key in _REF_KEYWORDS and isinstance(value, str):
                    out.append(value)
                else:
                    stack.append(value)
        elif isinstance(item, list):
            stack.extend(item)
    return out


def _no_remote(uri: str) -> Any:
    """Retriever that refuses every external document: schemas are self-contained, and a
    fetch would let a schema author reach internal hosts or local files (SSRF)."""
    raise ValueError(f"external schema {uri!r} is not allowed")


def _pointer(path: Any) -> str:
    return "".join(f"/{str(p).replace('~', '~0').replace('/', '~1')}" for p in path)


class InputValidator:
    """Compiled validator for one schema version; safe to share between requests."""

    def __init__(self, schema: dict[str, Any]) -> None:
        check_schema(schema)
        try:
            self._validator = jsonschema_rs.validator_for(
                schema, validate_formats=True, retriever=_no_remote
            )
        except (ValueError, jsonschema_rs.ValidationError) as exc:
            raise SchemaError(str(exc)) from exc

    def is_valid(self, instance: Any) -> bool:
        return bool(self._validator.is_valid(instance))

    def errors(self, instance: Any, limit: int = 50) -> list[dict[str, str]]:
        """Return up to ``limit`` errors as ``{"path": JSON pointer, "message": ...}``."""
        out: list[dict[str, str]] = []
        for err in self._validator.iter_errors(instance):
            out.append({"path": _pointer(err.instance_path), "message": err.message})
            if len(out) >= limit:
                break
        return out
