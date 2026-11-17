from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import orjson
import pytest
from fastapi.testclient import TestClient

import minos.api.app as module
from minos.api.app import create_app
from minos.api.exec_docs import embed_schema
from minos.settings import Settings

from .conftest import EXAMPLES, graph

EMBA = "/v1/exec/local/aurora.studyplan.emba"


def files(directory: Path) -> Settings:
    return Settings(
        database_url=None, rulesets_dir=directory, require_auth=False, poll_interval_s=30
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(files(EXAMPLES / "rulesets"))) as c:
        yield c


def test_health_and_listing(client: TestClient) -> None:
    assert client.get("/v1/health").json() == {"status": "ok", "deployments": 6}
    assert client.get("/v1/ready").json() == {"status": "ready"}
    listing = client.get("/v1/deployments").json()
    assert [d["ruleset"] for d in listing] == [
        "aurora.enrollment",
        "aurora.studyplan.common",
        "aurora.studyplan.emba",
        "aurora.studyplan.full",
        "bank.loan.eligibility",
        "shop.order",
    ]
    assert {d["workspace"] for d in listing} == {"local"}


def test_execute(client: TestClient, invalid_plan: dict[str, Any]) -> None:
    res = client.post(
        EMBA,
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
        ("/v1/exec/local/nope", b'{"input": {}}', 404),
        ("/v1/exec/local/aurora.studyplan.emba/versions/1.0.0", b'{"input": {}}', 404),
        (EMBA, b"{not json", 400),
        (EMBA, b"[]", 400),
        (EMBA, b'{"input": {}, "options": 3}', 400),
        (EMBA, b'{"input": {}, "options": {"trace": "all"}}', 400),
        (EMBA, b'{"input": "' + b"x" * 1_100_000 + b'"}', 413),
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
    with TestClient(create_app(files(tmp_path))) as client:
        assert client.post("/v1/exec/local/t.bad", json={"input": {}}).status_code == 422
        res = client.post("/v1/exec/local/t.limited", json={"input": {}})
        assert res.status_code == 422
        assert res.json()["title"] == "Execution Limit"
        res = client.post("/v1/exec/local/t.orphan", json={"input": {}})
        assert res.json()["outcome"] == "valid"


def test_rulesets_dir_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINOS_RULESETS_DIR", str(EXAMPLES / "rulesets"))
    monkeypatch.setenv("MINOS_REQUIRE_AUTH", "false")
    monkeypatch.delenv("MINOS_DATABASE_URL", raising=False)
    with TestClient(create_app()) as client:
        assert client.get("/v1/health").json()["deployments"] == 6


def test_zero_config_serves_examples_without_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("MINOS_RULESETS_DIR", "MINOS_DATABASE_URL", "MINOS_REQUIRE_AUTH"):
        monkeypatch.delenv(name, raising=False)
    with TestClient(create_app()) as client:
        assert client.post(EMBA, json={"input": {}}).status_code == 200
        info = client.get("/v1/info").json()
        assert info["authRequired"] is False
        assert info["management"] is False
        assert info["database"] is False


def test_auth_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MINOS_REQUIRE_AUTH", raising=False)
    assert Settings.from_env().require_auth is False
    monkeypatch.setenv("MINOS_REQUIRE_AUTH", "true")
    assert Settings.from_env().require_auth is True


def test_auth_without_database_is_rejected() -> None:
    settings = Settings(
        database_url=None, rulesets_dir=EXAMPLES / "rulesets", require_auth=True, poll_interval_s=30
    )
    with TestClient(create_app(settings)) as client:
        assert client.post(EMBA, json={"input": {}}).status_code == 401
        res = client.post(EMBA, json={"input": {}}, headers={"X-Api-Key": "k"})
        assert res.status_code == 401


def test_module_level_apps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MINOS_DATABASE_URL", raising=False)
    assert module.app.title == "Minos"
    assert module.execution_app.title == "Minos Execution API"
    with pytest.raises(RuntimeError):
        _ = module.management_app
    with pytest.raises(AttributeError):
        _ = module.nope


def test_file_mode_resolves_sub_rulesets(client: TestClient, valid_plan: dict[str, Any]) -> None:
    res = client.post("/v1/exec/local/aurora.studyplan.full", json={"input": valid_plan})
    assert res.status_code == 200
    assert res.json()["result"]["tuitionFee"] == 30800


def test_exec_openapi(client: TestClient) -> None:
    doc = client.get("/v1/exec/openapi.json").json()
    assert doc["openapi"] == "3.1.0"
    assert f"{EMBA}" in doc["paths"]
    op = doc["paths"]["/v1/exec/local/shop.order"]["post"]
    assert op["summary"] == "shop.order @ prod — v0.1.0"
    assert "`ORD_COUPON_IGNORED` | warning" in op["description"]
    assert "security" not in doc
    assert client.get("/v1/exec/openapi.json?workspace=nope").json()["paths"] == {}
    page = client.get("/v1/exec/docs")
    assert page.status_code == 200 and "swagger-ui" in page.text
    # documents of the deployments, not of the platform
    assert "/v1/exec/openapi.json" not in client.get("/openapi.json").json()["paths"]


def test_exec_openapi_follows_registry(client: TestClient) -> None:
    registry = client.app.state.runtime.registry  # type: ignore[attr-defined]
    first = client.get("/v1/exec/openapi.json").json()
    assert client.get("/v1/exec/openapi.json").json() == first
    registry.put(("local", "shop.order", "prod"), None)
    assert "/v1/exec/local/shop.order" not in client.get("/v1/exec/openapi.json").json()["paths"]


def test_embed_schema_rewrites_local_refs() -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:x",
        "type": "object",
        "properties": {"a": {"$ref": "#/$defs/A"}, "b": {"$ref": "other.json#/x"}},
        "$defs": {"A": {"type": "string"}},
    }
    out = embed_schema(schema, "W.R.prod.Input")
    assert out["properties"]["a"]["$ref"] == "#/components/schemas/W.R.prod.Input/$defs/A"
    assert out["properties"]["b"]["$ref"] == "other.json#/x"
    assert "$id" not in out and "$schema" not in out
    assert schema["properties"]["a"]["$ref"] == "#/$defs/A"  # input untouched
