# Minos backend

Motore di regole (`minos.engine`) ed Execution API (`minos.api`), Python 3.14.

```bash
uv sync                                  # dipendenze
uv run pytest                            # test + copertura (soglia 85%)
uv run ruff check . && uv run mypy       # lint e type-check
uv run python bench/bench_engine.py      # benchmark, gate G0
uv run uvicorn minos.api.app:app --reload
```

Esempio di chiamata con il rule set dimostrativo in `examples/rulesets`:

```bash
curl -s localhost:8000/v1/exec/gsom.studyplan.emba \
  -H 'content-type: application/json' \
  -d "{\"input\": $(cat ../examples/inputs/studyplan-emba-invalid.json), \"options\": {\"trace\": \"summary\"}}"
```
