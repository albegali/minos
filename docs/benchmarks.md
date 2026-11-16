# Benchmark e gate di fase

Misure su container Linux x86_64 condiviso, Python 3.14.6, PostgreSQL 16. Sono indicative:
vanno ripetute sull'hardware di produzione.

## G0 · motore (F0)

`backend/bench/bench_engine.py`: latenza del solo motore.

| Caso | p50 | p99 | Soglia p99 |
| --- | --- | --- | --- |
| Grafo sintetico 100 nodi, input 10 KB | ~0,55 ms | ~1,1–1,3 ms | 2 ms |
| Rule set Aurora EMBA | ~0,03 ms | ~0,1 ms | — |

## G1 · API (F1)

`backend/bench/bench_api.py`: database nuovo, migrazioni, pubblicazione degli esempi tramite la
Management API (con i test come gate), poi carico a ritmo costante (open loop) su
`POST /v1/exec/aurora/aurora.studyplan.emba` con autenticazione e validazione dello schema attive.
Server: uvicorn con **un solo worker** (un core). Latenza misurata dal client (HTTP, auth,
validazione schema, motore, serializzazione, loopback).

| Ritmo | Durata | Richieste | Errori | p50 | p95 | p99 | Motore p99 | Soglia p99 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 200 req/s | 20 s | 4.000 | 0 | 2,1 ms | 2,9 ms | 6,5 ms | 0,26 ms | 10 ms |

Il motore pesa circa il 5% della latenza: il resto è stack HTTP Python e client di carico sulla
stessa macchina. Le regole comuni Aurora (7 casi) e le regole EMBA (3 casi) passano i test al
momento della pubblicazione.

In CI le soglie sono più larghe (G0 3 ms, G1 20 ms) perché i runner condivisi sono rumorosi:
servono a intercettare regressioni, non a certificare i gate.

## G2 · editor (F2)

`frontend/e2e/g2.spec.ts` (Playwright, gira in CI con PostgreSQL). Un utente con chiave
`manage`, senza privilegi admin, dalla sola interfaccia:

1. crea l'entità e ne inferisce lo schema da due esempi;
2. crea il rule set, trascina una condizione sul canvas e la configura come "somma dei CFU dei
   corsi ≥ 60" con un messaggio di errore, senza scrivere JSON;
3. collega i nodi, sceglie la modalità "raccogli tutti gli errori", salva e valida;
4. simula un piano da 40 CFU, salva la simulazione come test ed esegue i test;
5. pubblica la versione 0.1.0 promuovendola in `test`.

Il test verifica poi, con una chiave `exec`, che l'Execution API risponda `valid` per il piano
da 60 CFU e `invalid` con `SP_CFU_MIN` per quello da 40. Durata circa 7 secondi.

Il gate G2 della roadmap prevede una prova d'uso con una persona reale dell'ufficio didattica:
questo test ne automatizza il percorso, ma non la sostituisce.
