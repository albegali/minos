"""OpenAPI document and Swagger UI for the deployed rule sets.

FastAPI's own ``/openapi.json`` describes the platform: one generic execution endpoint whose
``input`` is any object. This module describes what is actually deployed instead: one operation
per rule set and environment, with the entity schema as the request body and the feedback codes
the graph declares. It is derived from the in-memory :class:`RulesetRegistry`, so it follows
every publish, promotion and alias change as soon as the worker reloads (``NOTIFY`` or polling),
with no step of its own.
"""

from __future__ import annotations

import copy
import datetime as dt
import re
from typing import Any

from minos import __version__
from minos.db import ALWAYS

from .registry import DEFAULT_ENV, Deployment, Key, RulesetRegistry, Schedule, pick

SWAGGER_UI = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14"

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

_OPTIONS = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "trace": {"type": "string", "enum": ["none", "summary", "full"], "default": "none"},
        "locale": {"type": "string", "description": "Locale of the feedback messages"},
        "referenceDate": {
            "type": "string",
            "format": "date",
            "description": "Date the rules are evaluated on (default: today, UTC). It feeds "
            "today() and age() and picks the version when the environment has a schedule.",
        },
        "validateSchema": {"type": "boolean", "default": True},
    },
}

_FEEDBACK = {
    "type": "object",
    "required": ["code", "severity", "message", "nodeId"],
    "properties": {
        "code": {"type": "string"},
        "severity": {"type": "string", "enum": ["error", "warning", "info"]},
        "message": {"type": "string"},
        "nodeId": {"type": "string"},
        "path": {"type": "string"},
        "data": {"type": "object"},
    },
}

_RESULT = {
    "type": "object",
    "required": ["requestId", "ruleset", "version", "outcome", "feedback", "result", "path"],
    "properties": {
        "requestId": {"type": "string"},
        "ruleset": {"type": "string"},
        "version": {"type": "string"},
        "outcome": {"type": "string", "enum": ["valid", "invalid", "warning", "error"]},
        "exit": {
            "type": ["object", "null"],
            "properties": {"nodeId": {"type": "string"}, "reason": {"type": "string"}},
        },
        "feedback": {"type": "array", "items": {"$ref": "#/components/schemas/Feedback"}},
        "result": {"type": "object", "description": "Output of the end node reached"},
        "path": {"type": "array", "items": {"type": "string"}},
        "trace": {"type": ["array", "null"], "items": {"type": "object"}},
        "timing": {"type": "object", "properties": {"engineUs": {"type": "number"}}},
    },
}

_PROBLEM = {
    "type": "object",
    "required": ["status", "title", "detail"],
    "properties": {
        "status": {"type": "integer"},
        "title": {"type": "string"},
        "detail": {"type": "string"},
        "errors": {
            "type": "array",
            "description": "Schema violations (400), as JSON pointers",
            "items": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "message": {"type": "string"}},
            },
        },
    },
}

_HEADERS = {
    "X-Ruleset-Version": {"schema": {"type": "string"}, "description": "Version executed"},
    "X-Ruleset-Hash": {"schema": {"type": "string"}, "description": "Hash of that version"},
    "X-Request-Id": {"schema": {"type": "string"}},
}


def _problem(description: str) -> dict[str, Any]:
    return {
        "description": description,
        "content": {
            "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
        },
    }


def _component_name(*parts: str) -> str:
    return _UNSAFE.sub("_", ".".join(parts))


def embed_schema(schema: dict[str, Any], name: str) -> dict[str, Any]:
    """Make a standalone JSON Schema usable as ``#/components/schemas/<name>``: local
    references (``#/$defs/x``) are rewritten to point inside the component, and ``$id`` is
    dropped so that they resolve against the OpenAPI document."""
    base = f"#/components/schemas/{name}"

    def rewrite(value: Any) -> Any:
        if isinstance(value, dict):
            out = {}
            for k, v in value.items():
                if k == "$ref" and isinstance(v, str) and v.startswith("#"):
                    out[k] = base + v[1:]
                else:
                    out[k] = rewrite(v)
            return out
        if isinstance(value, list):
            return [rewrite(v) for v in value]
        return value

    embedded: dict[str, Any] = rewrite(copy.deepcopy(schema))
    embedded.pop("$id", None)
    embedded.pop("$schema", None)
    return embedded


def _current(schedule: Schedule, today: dt.date) -> Deployment:
    """The deployment in force today, else the first one scheduled."""
    return pick(schedule, today) or schedule[0][1]


def _describe(key: Key, schedule: Schedule, current: Deployment, today: dt.date) -> str:
    ws, rs, env = key
    lines = [f"Executes **{rs}** in workspace `{ws}`, environment `{env}`.", ""]
    lines.append("| From | Version | Hash |")
    lines.append("| --- | --- | --- |")
    for start, dep in schedule:
        when = "always" if start == ALWAYS else start.isoformat()
        marker = " (in force)" if pick(schedule, today) is dep else ""
        lines.append(f"| {when} | {dep.compiled.version}{marker} | `{dep.hash[:12]}` |")
    if current.feedback_codes:
        lines += ["", "Feedback codes declared by the rule set:", ""]
        lines.append("| Code | Severity |")
        lines.append("| --- | --- |")
        lines += [f"| `{code}` | {sev} |" for code, sev in current.feedback_codes]
    if current.schema is None:
        lines += ["", "No entity schema: `input` is not validated."]
    return "\n".join(lines)


def build_openapi(
    registry: RulesetRegistry,
    *,
    workspaces: frozenset[str] | None,
    require_auth: bool,
    today: dt.date | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """OpenAPI 3.1 document of the deployments of ``workspaces`` (``None``: all of them)."""
    today = today or dt.datetime.now(dt.UTC).date()
    schemas: dict[str, Any] = {
        "ExecuteOptions": _OPTIONS,
        "ExecutionResult": _RESULT,
        "Feedback": _FEEDBACK,
        "Problem": _PROBLEM,
    }
    paths: dict[str, Any] = {}
    tags: list[str] = []
    for key, schedule in sorted(registry.schedules().items()):
        ws, rs, env = key
        if workspaces is not None and ws not in workspaces:
            continue
        current = _current(schedule, today)
        if ws not in tags:
            tags.append(ws)
        input_schema: dict[str, Any] = {"type": "object"}
        if current.schema is not None:
            name = _component_name(ws, rs, env, "Input")
            schemas[name] = embed_schema(current.schema, name)
            input_schema = {"$ref": f"#/components/schemas/{name}"}
        target = rs if env == DEFAULT_ENV else f"{rs}@{env}"
        paths[f"/v1/exec/{ws}/{target}"] = {
            "post": {
                "tags": [ws],
                "operationId": _component_name("exec", ws, rs, env),
                "summary": f"{rs} @ {env} — v{current.compiled.version}",
                "description": _describe(key, schedule, current, today),
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["input"],
                                "properties": {
                                    "input": input_schema,
                                    "options": {"$ref": "#/components/schemas/ExecuteOptions"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "Outcome of the rules (`valid`, `invalid`, `warning`)",
                        "headers": _HEADERS,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ExecutionResult"}
                            }
                        },
                    },
                    "400": _problem("Malformed body, or input not matching the entity schema"),
                    "401": _problem("Missing or invalid API key"),
                    "403": _problem("The API key cannot execute in this workspace"),
                    "404": _problem("No deployment for the reference date"),
                    "413": _problem("Input larger than 1 MB"),
                    "422": {
                        "description": "Execution error or step limit exceeded",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ExecutionResult"}
                            },
                            "application/problem+json": {
                                "schema": {"$ref": "#/components/schemas/Problem"}
                            },
                        },
                    },
                },
            }
        }

    description = (
        "Rule sets deployed on this Minos installation, one operation per environment. "
        "The document is regenerated whenever a version is published to an environment or "
        "an alias changes. A fixed version can also be run at "
        "`POST /v1/exec/{workspace}/{ruleset}/versions/{semver}` with the same body."
    )
    if note:
        description += f"\n\n**{note}**"
    doc: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {"title": "Minos rule sets", "version": __version__, "description": description},
        "tags": [{"name": t} for t in tags],
        "paths": paths,
        "components": {"schemas": schemas},
    }
    if require_auth:
        doc["components"]["securitySchemes"] = {
            "bearer": {"type": "http", "scheme": "bearer", "description": "mns_... API key"},
            "apiKey": {"type": "apiKey", "in": "header", "name": "X-Api-Key"},
        }
        doc["security"] = [{"bearer": []}, {"apiKey": []}]
    return doc


class OpenApiCache:
    """Documents by (registry generation, day, visible workspaces): rebuilt only on change."""

    def __init__(self, registry: RulesetRegistry, require_auth: bool) -> None:
        self.registry = registry
        self.require_auth = require_auth
        self._generation = -1
        self._docs: dict[tuple[dt.date, frozenset[str] | None, str | None], dict[str, Any]] = {}

    def get(self, workspaces: frozenset[str] | None, note: str | None = None) -> dict[str, Any]:
        if self._generation != self.registry.generation or len(self._docs) > 256:
            self._docs = {}
            self._generation = self.registry.generation
        today = dt.datetime.now(dt.UTC).date()
        key = (today, workspaces, note)
        doc = self._docs.get(key)
        if doc is None:
            doc = build_openapi(
                self.registry,
                workspaces=workspaces,
                require_auth=self.require_auth,
                today=today,
                note=note,
            )
            self._docs[key] = doc
        return doc


def swagger_html() -> str:
    """Swagger UI on ``openapi.json`` next to the page. The authorisation entered with the
    *Authorize* button is kept in the browser and also sent when fetching the document, so that
    on installations with API keys a reload shows the rule sets the key can execute."""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Minos rule sets</title>
<link rel="stylesheet" href="{SWAGGER_UI}/swagger-ui.css">
</head>
<body>
<div id="swagger-ui"></div>
<script src="{SWAGGER_UI}/swagger-ui-bundle.js"></script>
<script>
  const spec = "openapi.json" + window.location.search;
  function storedAuth() {{
    try {{
      const auth = JSON.parse(localStorage.getItem("authorized") || "{{}}");
      if (auth.bearer && auth.bearer.value) return {{Authorization: "Bearer " + auth.bearer.value}};
      if (auth.apiKey && auth.apiKey.value) return {{"X-Api-Key": auth.apiKey.value}};
    }} catch (e) {{}}
    return {{}};
  }}
  window.ui = SwaggerUIBundle({{
    url: spec,
    dom_id: "#swagger-ui",
    deepLinking: true,
    persistAuthorization: true,
    requestInterceptor: (req) => {{
      if (req.loadSpec) Object.assign(req.headers, storedAuth());
      return req;
    }},
  }});
</script>
</body>
</html>
"""
