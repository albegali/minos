# 0003 · Espressioni come AST JSON a grammatica chiusa

- Stato: Accettata per l'AST JSON; Proposta per la sintassi testuale
- Data: 2026-11-16

## Contesto

L'editor no-code genera condizioni; gli utenti esperti vogliono anche scriverle. Le espressioni
devono essere sicure (niente codice arbitrario, niente loop infiniti), verificabili contro lo
schema e veloci.

## Decisione

- La forma canonica è un **AST JSON** (`{"op": ..., "left": ..., "right": ...}`,
  `{"fn": ..., "args": [...], "where": ..., "select": ...}`, `{"ref": "$.input..."}`), ispirato a
  JsonLogic ma con operatori tipizzati e funzioni di aggregazione. Riferimento completo in
  [`docs/rgd-format.md`](../rgd-format.md).
- Grammatica **chiusa**: solo gli operatori e le funzioni registrati nel compiler; niente `eval`.
  I filtri sugli array usano `where` con `$.item` invece di JSONPath `[?()]`.
- I riferimenti assenti valgono `MISSING`: i confronti restituiscono `false`, le operazioni
  aritmetiche `null`, gli errori di tipo diventano `EvaluationError` (esito `error`).

## Da decidere (entro F1)

- Sintassi testuale per utenti esperti, parsata nel compiler con Lark: linguaggio proprio oppure un
  sottoinsieme compatibile con CEL o FEEL.
- Type-check delle espressioni contro lo schema dell'entità (oggi i path sono validati solo
  sintatticamente).
