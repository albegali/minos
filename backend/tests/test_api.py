from __future__ import annotations

from pathlib import Path
from typing import Any

import orjson
import pytest
from fastapi.testclient import TestClient

from minos.api.app import create_app

from .conftest import EXAMPLES, graph


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(EXAMPLES / "rulesets"))


def test_health_and_listing(client: TestClient) -> None:
    assert client.get("/v1/health").json() == {"status": "ok", "rulesets": 1}
    listing = client.get("/v1/rulesets").json()
    assert listing[0]["ruleset"] == "aurora.studyplan.emba"


def test_execute(client: TestClient, invalid_plan: dict[str, Any]) -> None:
    res = client.post(
        "/v1/exec/aurora.studyplan.emba",
        json={
            "input": invalid_plan,
            "options": {"trace": "summary", "referenceDate": "2027-09-20"},
        },
        headers={"x-request-id": "req-1"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["outcome"] == "invalid"
    assert body["requestId"] == "req-1"
    assert len(body["trace"]) == len(body["path"])
    assert res.headers["x-ruleset-version"] == "0.1.0"
    assert res.headers["server-timing"].startswith("engine;dur=")


@pytest.mark.parametrize(
    ("path", "payload", "status"),
    [
        ("/v1/exec/nope", b'{"input": {}}', 404),
        ("/v1/exec/aurora.studyplan.emba", b"{not json", 400),
        ("/v1/exec/aurora.studyplan.emba", b"[]", 400),
        ("/v1/exec/aurora.studyplan.emba", b'{"input": {}, "options": 3}', 400),
        ("/v1/exec/aurora.studyplan.emba", b'{"input": {}, "options": {"trace": "all"}}', 400),
        ("/v1/exec/aurora.studyplan.emba", b'{"input": "' + b"x" * 1_100_000 + b'"}', 413),
    ],
)
def test_errors(client: TestClient, path: str, payload: bytes, status: int) -> None:
    res = client.post(path, content=payload, headers={"content-type": "application/json"})
    assert res.status_code == status
    assert res.json()["status"] == status


def test_error_outcome_and_limits(tmp_path: Path) -> None:
    bad = graph(
        [
            {"id": "start", "type": "start"},
            {"id": "c", "type": "condition", "condition": {"op": "<", "left": "a", "right": 1}},
            {"id": "end", "type": "end", "outcome": "valid"},
        ],
        [{"from": "start", "to": "c"}, {"from": "c", "to": "end", "on": "pass"}],
        ruleset="t.bad",
    )
    limited = dict(bad, ruleset="t.limited", settings={"maxSteps": 1})
    orphan = graph(
        [
            {"id": "start", "type": "start"},
            {"id": "end", "type": "end", "outcome": "valid"},
            {"id": "x", "type": "end", "outcome": "valid"},
        ],
        [{"from": "start", "to": "end"}],
        ruleset="t.orphan",
    )
    for doc in (bad, limited, orphan):
        (tmp_path / f"{doc['ruleset']}.json").write_bytes(orjson.dumps(doc))
    client = TestClient(create_app(tmp_path))
    assert client.post("/v1/exec/t.bad", json={"input": {}}).status_code == 422
    res = client.post("/v1/exec/t.limited", json={"input": {}})
    assert res.status_code == 422
    assert res.json()["title"] == "Execution Limit"
    assert client.post("/v1/exec/t.orphan", json={"input": {}}).json()["outcome"] == "valid"


def test_rulesets_dir_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINOS_RULESETS_DIR", str(EXAMPLES / "rulesets"))
    client = TestClient(create_app())
    assert client.get("/v1/health").json()["rulesets"] == 1
