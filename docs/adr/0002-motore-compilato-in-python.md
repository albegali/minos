# 0002 · Motore compilato a closure in Python puro

- Stato: Accettata
- Data: 2026-11-16

## Contesto

Il backend è in Python. Un interprete che visita l'AST a ogni chiamata rischia di non rispettare il
gate G0 (p99 sotto 2 ms su un grafo da 100 nodi con input da 10 KB). Esistono motori nativi con
binding Python (es. `zen-engine` di GoRules, core in Rust).

## Decisione

- Alla pubblicazione il **compiler** valida il grafo (porte, DAG, raggiungibilità) e trasforma ogni
  nodo ed espressione in **closure Python** pre-costruite: i path diventano accessor, gli operatori
  funzioni specializzate (es. confronto con letterale senza normalizzazione), le regex sono
  precompilate, i template dei messaggi spezzati in parti.
- Il **runtime** cammina il grafo seguendo una porta per nodo, senza parsing né validazione Pydantic.
- Le aggregazioni con `where`/`select` legano `$.item` sul posto invece di copiare lo scope.

## Risultati dello spike (gate G0)

`backend/bench/bench_engine.py`, Python 3.14.6, x86_64, container condiviso:

| Caso | p50 | p99 |
| --- | --- | --- |
| Grafo sintetico, 100 nodi, input 10 KB, 25 aggregazioni su 70 elementi | ~0,55 ms | ~1,1–1,3 ms |
| Rule set Aurora EMBA (10 nodi), piano non valido | ~0,03 ms | ~0,08–0,14 ms |

Il gate G0 è superato. Il primo profilo mostrava il tempo dominato dal confronto `==` dentro i
`where`; la specializzazione sui letterali ha ridotto p99 di circa il 30%.

## Alternative e piano B

- Il confronto diretto con `zen-engine` previsto in F0 **non è stato eseguito**: viene rinviato a
  quando serviranno le decision table (F3), dove il vantaggio di un core nativo è più probabile.
- Se rule set reali superano i target: riscrivere il runtime in Rust con PyO3 mantenendo il formato
  RGD, oppure delegare singoli nodi (decision table) a un motore nativo.

## Conseguenze

- Il benchmark gira in CI come test di regressione con soglia `MINOS_BENCH_P99_MS=3.0`: i runner
  condivisi sono più rumorosi dell'hardware di riferimento su cui si misura il gate (2 ms).
- Le funzioni e gli operatori nuovi vanno aggiunti al compiler, non interpretati a runtime.
