# Minos

**Minos** è un motore di regole JSON-in / JSON-out: valuta un oggetto JSON contro un grafo di regole
versionato e restituisce esito, punto di uscita e feedback strutturati, con latenza sub-millisecondo.

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
| [`examples/`](examples/) | Rule set Aurora (regole comuni ed EMBA, valori illustrativi), input e suite di test |
| [`docs/spec.md`](docs/spec.md) | Specifiche funzionali, architettura, API e roadmap |
| [`docs/rgd-format.md`](docs/rgd-format.md) | Riferimento del formato Rule Graph Document 1.0 |
| [`docs/studio.md`](docs/studio.md) | Guida rapida a Minos Studio |
| [`docs/api.md`](docs/api.md) | Riferimento delle API di esecuzione e gestione |
| [`docs/benchmarks.md`](docs/benchmarks.md) | Misure e gate di fase |
| [`docs/adr/`](docs/adr/) | Decisioni architetturali |

## Avvio rapido

Requisiti: [uv](https://docs.astral.sh/uv/), Node.js 22 o superiore (CI su Node 24 LTS) e, per
la piattaforma completa, PostgreSQL 16 o 17.

### Demo senza database

```bash
cd backend && uv sync && uv run uvicorn minos.api.app:app --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

Senza configurazione l'API serve gli esempi di `examples/rulesets` come workspace `local`, senza
autenticazione. Apri http://localhost:5173/demo, scegli un input e premi **Simula**.

### Piattaforma completa

```bash
export MINOS_DATABASE_URL=postgresql+asyncpg://minos:minos@localhost:5432/minos
```

```bash
cd backend && uv run python -m minos.cli migrate && uv run python -m minos.cli create-admin-key --name me
```

```bash
uv run uvicorn minos.api.app:app --port 8000
```

```bash
cd frontend && npm run dev
```

Apri http://localhost:5173 e accedi con la chiave admin (o con una chiave `manage` del
workspace): la [guida allo Studio](docs/studio.md) descrive il percorso completo.

Con la chiave admin si creano workspace, entità, schemi e rule set, si pubblica e si promuove a
`prod`: il flusso completo è in [`docs/api.md`](docs/api.md) e, eseguibile, in
`backend/bench/bench_api.py` (funzione `seed`). In produzione Execution API e Management API girano
come processi separati (`minos.api.app:execution_app`, `minos.api.app:management_app`).

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
