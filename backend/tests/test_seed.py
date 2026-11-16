"""Loading the repository examples into workspace "esempi" (``minos seed-examples``)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from minos.api.app import create_app
from minos.cli import main
from minos.control.examples import load_examples

from .test_platform import settings

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def test_examples_are_ordered_by_dependency() -> None:
    examples = load_examples(EXAMPLES)
    keys = [g["ruleset"] for g in examples.graphs]
    assert keys.index("aurora.studyplan.common") < keys.index("aurora.studyplan.emba")
    assert keys.index("aurora.studyplan.emba") < keys.index("aurora.studyplan.full")
    assert set(examples.samples) == {"StudyPlan", "Order", "LoanApplication"}
    assert all(examples.samples.values())
    assert all(examples.tests[k] for k in keys)


def test_seed_examples(
    clean_db: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MINOS_DATABASE_URL", clean_db)
    assert main(["seed-examples", "--dir", str(EXAMPLES)]) == 0
    out = capsys.readouterr().out
    assert "shop.order@0.1.0" in out and "aurora.studyplan.full@0.1.0" in out

    # a second start leaves the workspace (and what was changed in the Studio) alone
    assert main(["seed-examples", "--dir", str(EXAMPLES)]) == 0
    assert "already exists" in capsys.readouterr().out
    assert main(["seed-examples", "--dir", str(EXAMPLES / "missing")]) == 2

    asyncio.run(_execute_examples(clean_db))


async def _execute_examples(url: str) -> None:
    app = create_app(settings(url, require_auth=False, rulesets_dir=EXAMPLES / "rulesets"))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://m") as c,
    ):
        await app.state.runtime.sync.load_all()
        workspaces = (await c.get("/v1/workspaces")).json()
        assert [w["slug"] for w in workspaces] == ["esempi"]
        entities = (await c.get("/v1/workspaces/esempi/entities")).json()
        assert {e["name"] for e in entities} == {
            "Piano di studi",
            "Ordine",
            "Richiesta di finanziamento",
        }

        plan = json.loads((EXAMPLES / "inputs" / "studyplan-emba-valid.json").read_text())
        for ws in ("esempi", "local"):  # the Studio workspace and the read-only /demo one
            res = await c.post(f"/v1/exec/{ws}/aurora.studyplan.full", json={"input": plan})
            assert res.status_code == 200, res.text
            assert res.json()["outcome"] == "valid"
