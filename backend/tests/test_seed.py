"""Loading the repository examples into workspace "esempi" (``minos seed-examples``)."""

from __future__ import annotations

import asyncio
import json
import shutil
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
    # hand-written schemas come after the entities they reference
    order = examples.entities()
    assert order.index("Course") < order.index("Program") < order.index("Enrollment")
    assert order.index("Student") < order.index("Enrollment")
    assert all(examples.tests[k] for k in keys)


def test_seed_examples(
    clean_db: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MINOS_DATABASE_URL", clean_db)
    # an older repository, without the enrollment example
    older = tmp_path / "examples"
    shutil.copytree(EXAMPLES, older)
    shutil.rmtree(older / "entities")
    (older / "rulesets" / "aurora.enrollment.json").unlink()
    assert main(["seed-examples", "--dir", str(older)]) == 0
    out = capsys.readouterr().out
    assert "shop.order@0.1.0" in out and "aurora.studyplan.full@0.1.0" in out
    assert "aurora.enrollment" not in out

    # a later start adds only what is missing, leaving the rest (and Studio changes) alone
    assert main(["seed-examples", "--dir", str(EXAMPLES)]) == 0
    out = capsys.readouterr().out
    assert "published aurora.enrollment@0.1.0 in prod" in out and "shop.order" not in out
    assert main(["seed-examples", "--dir", str(EXAMPLES)]) == 0
    assert "nothing to add" in capsys.readouterr().out
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
            "Studente",
            "Corso",
            "Programma",
            "Piano individuale",
            "Iscrizione",
        }
        enrollment = (await c.get("/v1/workspaces/esempi/entities/Enrollment/schemas/1")).json()
        assert {r["entity"] for r in enrollment["references"]} == {"Student", "Program", "Plan"}
        used = (await c.get("/v1/workspaces/esempi/entities/Course")).json()["usedBy"]
        assert used == ["Program"]

        plan = json.loads((EXAMPLES / "inputs" / "studyplan-emba-valid.json").read_text())
        for ws in ("esempi", "local"):  # the Studio workspace and the read-only /demo one
            res = await c.post(f"/v1/exec/{ws}/aurora.studyplan.full", json={"input": plan})
            assert res.status_code == 200, res.text
            assert res.json()["outcome"] == "valid"

        bad = json.loads((EXAMPLES / "inputs" / "enrollment-invalid.json").read_text())
        res = await c.post(
            "/v1/exec/esempi/aurora.enrollment",
            json={"input": bad, "options": {"referenceDate": "2027-09-20"}},
        )
        assert res.status_code == 200, res.text
        assert [f["code"] for f in res.json()["feedback"]] == [
            "EN_AGE_MIN",
            "EN_COURSE_NOT_OFFERED",
            "EN_COURSE_DUPLICATE",
            "EN_MANDATORY_MISSING",
            "EN_CFU_RANGE",
        ]


def test_seed_skips_examples_that_do_not_fit(
    clean_db: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # an entity made in the Studio, then an upgrade adds an example rule set on it (CTL-05)
    monkeypatch.setenv("MINOS_DATABASE_URL", clean_db)
    older = tmp_path / "examples"
    shutil.copytree(EXAMPLES, older)
    (older / "rulesets" / "shop.order.json").unlink()
    assert main(["seed-examples", "--dir", str(older)]) == 0
    asyncio.run(_edit_order_schema(clean_db))
    capsys.readouterr()
    assert main(["seed-examples", "--dir", str(EXAMPLES)]) == 0  # the start-up goes on
    out, err = capsys.readouterr()
    assert "example skipped: shop.order" in err
    assert "nothing to add" in out


async def _edit_order_schema(url: str) -> None:
    app = create_app(settings(url, require_auth=False))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://m") as c,
    ):
        # an entity of the same key, made in the Studio with another shape
        r = await c.post("/v1/workspaces/esempi/entities", json={"key": "Order", "name": "Mine"})
        assert r.status_code == 201, r.text
        body = {"schema": {"type": "object", "properties": {"id": {"type": "string"}}}}
        r = await c.post("/v1/workspaces/esempi/entities/Order/schemas", json=body)
        assert r.status_code == 201, r.text
