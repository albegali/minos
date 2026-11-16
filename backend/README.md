# Minos backend

Motore (`minos.engine`), schemi (`minos.schema`), control plane (`minos.control`, `minos.db`) e API
(`minos.api`), Python 3.14. I test che usano PostgreSQL leggono `MINOS_TEST_DATABASE_URL`
(default `postgresql+asyncpg://minos:minos@localhost:5432/minos_test`) e vengono saltati se il
database non è raggiungibile.

```bash
uv sync                                  # dipendenze
uv run pytest                            # test + copertura (soglia 85%)
uv run ruff check . && uv run mypy       # lint e type-check
uv run python bench/bench_engine.py      # benchmark del motore, gate G0
uv run python bench/bench_api.py         # load test dell'API su PostgreSQL, gate G1
uv run uvicorn minos.api.app:app --reload
```

Esempio di chiamata con il rule set dimostrativo in `examples/rulesets`:

```bash
curl -s localhost:8000/v1/exec/local/gsom.studyplan.emba \
  -H 'content-type: application/json' \
  -d "{\"input\": $(cat ../examples/inputs/studyplan-emba-invalid.json), \"options\": {\"trace\": \"summary\"}}"
```
