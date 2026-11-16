from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"


def load_json(relative: str) -> Any:
    return json.loads((EXAMPLES / relative).read_text())


@pytest.fixture
def aurora_graph() -> dict[str, Any]:
    data: dict[str, Any] = load_json("rulesets/aurora.studyplan.emba.json")
    return data


@pytest.fixture
def valid_plan() -> dict[str, Any]:
    data: dict[str, Any] = load_json("inputs/studyplan-emba-valid.json")
    return data


@pytest.fixture
def invalid_plan() -> dict[str, Any]:
    data: dict[str, Any] = load_json("inputs/studyplan-emba-invalid.json")
    return data


def graph(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    """Minimal RGD wrapper used by the unit tests."""
    doc: dict[str, Any] = {"rgdVersion": "1.0", "ruleset": "t.test", "nodes": nodes, "edges": edges}
    doc.update(extra)
    return doc
