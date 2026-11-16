# 0001 · Storage delle regole: PostgreSQL + cache in memoria

- Stato: Accettata
- Data: 2026-11-16

## Contesto

Le API di esecuzione devono rispondere in tempo reale (p99 lato server sotto 10 ms, motore sotto
2 ms) e costare poco. Le regole cambiano raramente rispetto a quante volte vengono eseguite.

## Decisione

- **PostgreSQL** è la fonte di verità per schemi, grafi, versioni immutabili, alias, test e audit
  (JSONB per i documenti, tabelle relazionali per identità e permessi).
- Ogni worker dell'Execution API tiene in **RAM** le versioni compilate degli alias attivi
  (`RulesetRegistry`), con sostituzione atomica del dizionario.
- Invalidazione con **`LISTEN/NOTIFY`** di PostgreSQL alla pubblicazione o al cambio di alias, più
  un polling di sicurezza ogni 30 s sugli hash.
- Nessun database sul percorso caldo di una chiamata.

## Alternative scartate

- Redis come store primario: aggiunge 0,2–1 ms per chiamata e un servizio da gestire.
- MongoDB/Cosmos DB letti a ogni richiesta: latenza e costo maggiori, richiedono comunque cache.
- Object storage: ottimo per distribuire bundle multi-regione (fase F5), non per l'editing.

## Conseguenze

- In F0 il registry si popola da file (`examples/rulesets`); in F1 da PostgreSQL, con la stessa API.
- L'Execution API continua a servire anche se il database è irraggiungibile.
- Va misurato il drift tra worker (hash di versione nell'header `X-Ruleset-Version`).
