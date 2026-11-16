# Benchmark e gate di fase

Misure su container Linux x86_64 condiviso, Python 3.14.6, PostgreSQL 16. Sono indicative:
vanno ripetute sull'hardware di produzione.

## G0 · motore (F0)

`backend/bench/bench_engine.py`: latenza del solo motore.

| Caso | p50 | p99 | Soglia p99 |
| --- | --- | --- | --- |
| Grafo sintetico 100 nodi, input 10 KB | ~0,55 ms | ~1,1–1,3 ms | 2 ms |
| Rule set GSoM EMBA | ~0,03 ms | ~0,1 ms | — |

## G1 · API (F1)

`backend/bench/bench_api.py`: database nuovo, migrazioni, pubblicazione degli esempi tramite la
Management API (con i test come gate), poi carico a ritmo costante (open loop) su
`POST /v1/exec/gsom/gsom.studyplan.emba` con autenticazione e validazione dello schema attive.
Server: uvicorn con **un solo worker** (un core). Latenza misurata dal client (HTTP, auth,
validazione schema, motore, serializzazione, loopback).

| Ritmo | Durata | Richieste | Errori | p50 | p95 | p99 | Motore p99 | Soglia p99 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 200 req/s | 20 s | 4.000 | 0 | 2,1 ms | 2,9 ms | 6,5 ms | 0,26 ms | 10 ms |

Il motore pesa circa il 5% della latenza: il resto è stack HTTP Python e client di carico sulla
stessa macchina. Le regole comuni GSoM (7 casi) e le regole EMBA (3 casi) passano i test al
momento della pubblicazione.

In CI le soglie sono più larghe (G0 3 ms, G1 20 ms) perché i runner condivisi sono rumorosi:
servono a intercettare regressioni, non a certificare i gate.
