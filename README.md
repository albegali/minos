# Minos

**Minos** è un motore di regole JSON-in / JSON-out: valuta un oggetto JSON contro un grafo di regole
versionato e restituisce esito, punto di uscita e feedback strutturati, con latenza sub-millisecondo.

> Come Minosse, re e legislatore di Creta e poi giudice delle anime, Minos giudica ogni oggetto
> e decide da che parte farlo passare.

Stato: **fase F0 (fondamenta)** della [roadmap](docs/spec.md#roadmap).

## Struttura

| Percorso | Contenuto |
| --- | --- |
| [`backend/`](backend/) | Python 3.14: motore (`minos.engine`), Execution API FastAPI (`minos.api`), test, benchmark |
| [`frontend/`](frontend/) | Minos Studio: React 19 + React Flow, anteprima del canvas e simulatore |
| [`examples/`](examples/) | Rule set dimostrativo (piano di studi EMBA, valori illustrativi) e input di esempio |
| [`docs/spec.md`](docs/spec.md) | Specifiche funzionali, architettura, API e roadmap |
| [`docs/rgd-format.md`](docs/rgd-format.md) | Riferimento del formato Rule Graph Document 1.0 |
| [`docs/adr/`](docs/adr/) | Decisioni architetturali |

## Avvio rapido

Requisiti: [uv](https://docs.astral.sh/uv/) e Node.js 22 o superiore (CI su Node 24 LTS).

```bash
cd backend && uv sync && uv run uvicorn minos.api.app:app --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

Apri http://localhost:5173, scegli un input e premi **Simula**: lo Studio chiama l'API, evidenzia il
percorso eseguito e mostra feedback e output.

Chiamata diretta all'API:

```bash
curl -s localhost:8000/v1/exec/aurora.studyplan.emba \
  -H 'content-type: application/json' \
  -d "{\"input\": $(cat examples/inputs/studyplan-emba-invalid.json), \"options\": {\"trace\": \"summary\"}}"
```

## Qualità

```bash
cd backend && uv run ruff check . && uv run mypy && uv run pytest && uv run python bench/bench_engine.py
```

```bash
cd frontend && npm run lint && npm run build
```
