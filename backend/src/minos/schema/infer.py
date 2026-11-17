"""Inference of a JSON Schema (draft 2020-12) from one or more example objects.

Rules:

* types are merged across samples (``integer`` + ``number`` -> ``number``; anything + ``null``
  -> a nullable type list);
* an object property is ``required`` only if it appears in every sample that has the object;
* array item schemas are merged over every element of every sample;
* strings get a ``format`` (``date-time``, ``date``, ``email``, ``uuid``) when every observed
  value matches it.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Final

import jsonschema_rs

SCHEMA_DIALECT: Final = "https://json-schema.org/draft/2020-12/schema"

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")


_FORMAT_CHECKS: dict[str, Any] = {}


def _accepted(value: str, fmt: str) -> bool:
    """Whether the input validator accepts ``value`` for ``fmt``: a format is inferred only if
    the samples it comes from would pass validation (its rules are stricter than these
    patterns, e.g. a date-time needs an offset)."""
    check = _FORMAT_CHECKS.get(fmt)
    if check is None:
        check = jsonschema_rs.validator_for(
            {"type": "string", "format": fmt}, validate_formats=True
        )
        _FORMAT_CHECKS[fmt] = check
    return bool(check.is_valid(value))


def _string_format(value: str) -> str | None:
    fmt = _candidate_format(value)
    return fmt if fmt is not None and _accepted(value, fmt) else None


def _candidate_format(value: str) -> str | None:
    if _DATE.match(value):
        try:
            dt.date.fromisoformat(value)
        except ValueError:
            return None
        return "date"
    if _DATETIME.match(value):
        try:
            dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return "date-time"
    if _UUID.match(value):
        return "uuid"
    if _EMAIL.match(value):
        return "email"
    return None


@dataclass
class _Shape:
    types: set[str] = field(default_factory=set)
    properties: dict[str, _Shape] = field(default_factory=dict)
    required: set[str] | None = None
    items: _Shape | None = None
    formats: set[str | None] = field(default_factory=set)
    examples: list[Any] = field(default_factory=list)

    def add(self, value: Any) -> None:
        if value is None:
            self.types.add("null")
        elif isinstance(value, bool):
            self.types.add("boolean")
            self._example(value)
        elif isinstance(value, int):
            self.types.add("integer")
            self._example(value)
        elif isinstance(value, float):
            self.types.add("number")
            self._example(value)
        elif isinstance(value, str):
            self.types.add("string")
            self.formats.add(_string_format(value))
            self._example(value)
        elif isinstance(value, list):
            self.types.add("array")
            if self.items is None:
                self.items = _Shape()
            for item in value:
                self.items.add(item)
        elif isinstance(value, dict):
            self.types.add("object")
            keys = set(value)
            self.required = keys if self.required is None else self.required & keys
            for key, child in value.items():
                self.properties.setdefault(key, _Shape()).add(child)
        else:
            raise TypeError(f"not a JSON value: {type(value).__name__}")

    def _example(self, value: Any) -> None:
        if len(self.examples) < 1 and value not in self.examples:
            self.examples.append(value)

    def to_schema(self) -> dict[str, Any]:
        types = set(self.types)
        if {"integer", "number"} <= types:
            types.discard("integer")
        out: dict[str, Any] = {}
        if not types:
            return out  # empty array: items unknown, accept anything
        ordered = sorted(types - {"null"}) + (["null"] if "null" in types else [])
        out["type"] = ordered[0] if len(ordered) == 1 else ordered
        if "string" in types and len(self.formats) == 1:
            fmt = next(iter(self.formats))
            if fmt is not None:
                out["format"] = fmt
        if "object" in types:
            out["properties"] = {k: s.to_schema() for k, s in self.properties.items()}
            if self.required:
                out["required"] = sorted(self.required)
        if "array" in types:
            out["items"] = self.items.to_schema() if self.items else {}
        if self.examples and types & {"string", "integer", "number"}:
            out["examples"] = list(self.examples)
        return out


def infer_schema(samples: Iterable[Any], *, title: str | None = None) -> dict[str, Any]:
    """Infer a draft 2020-12 JSON Schema describing every sample."""
    shape = _Shape()
    count = 0
    for sample in samples:
        shape.add(sample)
        count += 1
    if count == 0:
        raise ValueError("at least one sample is required")
    schema: dict[str, Any] = {"$schema": SCHEMA_DIALECT}
    if title:
        schema["title"] = title
    schema.update(shape.to_schema())
    return schema
