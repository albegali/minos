# Minos

**Minos** è un motore di regole JSON-in / JSON-out: valuta un oggetto JSON contro un grafo di regole
versionato e restituisce esito, punto di uscita e feedback strutturati, con latenza sub-millisecondo.
È generico: gli esempi coprono un piano di studi universitario, un ordine e-commerce e
l'idoneità a un finanziamento, ma qualunque oggetto JSON con uno schema può essere validato.

> Come Minosse, re e legislatore di Creta e poi giudice delle anime, Minos giudica ogni oggetto
> e decide da che parte farlo passare.

Stato: **fase F2 (editor MVP)** della [roadmap](docs/spec.md#roadmap): motore compilato, control plane su
PostgreSQL con versioni e alias, Execution API con hot reload, Minos Studio per costruire, testare e
pubblicare le regole senza scrivere JSON.

## Struttura

| Percorso | Contenuto |
| --- | --- |
| [`backend/`](backend/) | Python 3.14: motore (`minos.engine`), schemi (`minos.schema`), control plane (`minos.control`, `minos.db`), API FastAPI (`minos.api`), test, benchmark |
| [`frontend/`](frontend/) | Minos Studio: React 19, Fluent UI 2, React Flow; test Vitest e Playwright |
| [`examples/`](examples/) | Rule set di esempio di tre domini (piano di studi, ordine e-commerce, finanziamento; valori illustrativi), input e suite di test |
| [`docs/spec.md`](docs/spec.md) | Specifiche funzionali, architettura, API e roadmap |
| [`docs/rgd-format.md`](docs/rgd-format.md) | Riferimento del formato Rule Graph Document 1.0 |
| [`docs/studio.md`](docs/studio.md) | Guida rapida a Minos Studio |
| [`docs/api.md`](docs/api.md) | Riferimento delle API di esecuzione e gestione |
| [`docs/benchmarks.md`](docs/benchmarks.md) | Misure e gate di fase |
| [`docs/adr/`](docs/adr/) | Decisioni architetturali |

## Avvio rapido

Con Docker, un solo comando avvia PostgreSQL, API e Studio:

```bash
docker compose up --build
```

Apri http://localhost:8080 (Studio) e http://localhost:8000/v1/info (API). L'installazione è
**aperta**: nessun login, pensata per l'uso in locale. Per richiedere le API key, imposta
`MINOS_REQUIRE_AUTH=true` (vedi [`docs/api.md`](docs/api.md)). La
[guida allo Studio](docs/studio.md) descrive il percorso completo, dall'entità alla pubblicazione.

### Sviluppo senza Docker

Requisiti: [uv](https://docs.astral.sh/uv/), Node.js 22 o superiore (CI su Node 24 LTS),
PostgreSQL 16 o 17.

```bash
export MINOS_DATABASE_URL=postgresql+asyncpg://minos:minos@localhost:5432/minos
```

```bash
cd backend && uv sync && uv run python -m minos.cli migrate && uv run uvicorn minos.api.app:app --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

Studio su http://localhost:5173. Senza `MINOS_DATABASE_URL` l'API serve in sola lettura gli esempi
di `examples/rulesets` e lo Studio apre la demo (`/demo`).

In un'installazione più grande Execution API e Management API girano come processi separati
(`minos.api.app:execution_app`, `minos.api.app:management_app`).

## Qualità

```bash
cd backend && uv run ruff check . && uv run mypy && uv run pytest && uv run python bench/bench_engine.py && uv run python bench/bench_api.py
```

```bash
cd frontend && npm run lint && npm test && npm run build
```

```bash
cd frontend && npm run e2e   # Playwright: avvia API e Studio su un database nuovo (PostgreSQL locale)
```

## Licenza

[MIT](LICENSE).
