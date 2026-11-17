# Minos backend

Engine (`minos.engine`), schemas (`minos.schema`), control plane (`minos.control`, `minos.db`) and
API (`minos.api`), Python 3.14. Tests that use PostgreSQL read `MINOS_TEST_DATABASE_URL`
(default `postgresql+asyncpg://minos:minos@localhost:5432/minos_test`) and are skipped if the
database is unreachable.

```bash
uv sync                                  # dependencies
uv run pytest                            # tests + coverage (85% threshold)
uv run ruff check . && uv run mypy       # lint and type-check
uv run python bench/bench_engine.py      # engine benchmark, gate G0
uv run python bench/bench_api.py         # API load test on PostgreSQL, gate G1
uv run uvicorn minos.api.app:app --reload
```

Example call with the demo rule set in `examples/rulesets`:

```bash
curl -s localhost:8000/v1/exec/local/aurora.studyplan.emba \
  -H 'content-type: application/json' \
  -d "{\"input\": $(cat ../examples/inputs/studyplan-emba-invalid.json), \"options\": {\"trace\": \"summary\"}}"
```
