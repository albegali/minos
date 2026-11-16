# 0006 · Server MCP sopra la Management API, solo draft

- Stato: Accettata
- Data: 2026-11-16

## Contesto

Vogliamo che chi conosce il dominio descriva le regole a parole in un client AI (Claude Desktop,
Claude Code, altri) e che l'assistente le traduca in entità e rule set Minos, lasciando a una
persona la revisione nello Studio. Il protocollo standard per dare strumenti a un assistente è
MCP (Model Context Protocol).

## Decisione

- **Strato sottile sulla Management API.** I tool (`minos.mcp`, SDK `mcp` 2.x) chiamano gli
  endpoint HTTP esistenti invece del service layer: valgono la stessa validazione, il lock
  ottimistico dei draft (`If-Match`), l'audit e gli scope delle API key, e lo stesso server
  funziona verso qualunque installazione.
- **Due trasporti.** Streamable HTTP su `/mcp` dell'API combinata (le chiamate restano nel
  processo tramite ASGI, inoltrando la chiave del client); stdio con `python -m minos.mcp` verso
  `MINOS_API_URL` (chiave da `MINOS_API_KEY`).
- **Solo draft.** I tool creano e modificano workspace, entità, schemi, draft e test, validano e
  simulano; **non pubblicano** e non spostano ambienti. Ogni scrittura restituisce il link allo
  Studio (`MINOS_STUDIO_URL`), dove una persona rivede e pubblica; i test salvati restano il gate.
- **Il modello impara il formato dal server.** Il tool `guide` restituisce flusso di lavoro,
  esempio completo e `docs/rgd-format.md` (copia nel pacchetto, verificata identica da un test);
  le risposte di validazione dicono cosa correggere.
- Endpoint HTTP con protezione da DNS rebinding dell'SDK: accetta solo host locali, coerente
  con l'installazione locale.

## Conseguenze

- Un assistente non può mettere in produzione regole non riviste; con le API key attive, può fare
  solo ciò che consente la chiave usata.
- Nessuna logica duplicata: una nuova funzione della Management API diventa un tool con poche righe.
- Per esporre `/mcp` oltre `localhost` servirà configurare gli host ammessi (oggi non previsto).
