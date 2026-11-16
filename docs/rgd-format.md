# Rule Graph Document (RGD) · formato 1.0

Un rule set è un documento JSON che descrive un grafo orientato aciclico di nodi. Il modello
autoritativo è `backend/src/minos/engine/model.py`; esempio completo in
[`examples/rulesets/gsom.studyplan.emba.json`](../examples/rulesets/gsom.studyplan.emba.json).

```json
{
  "rgdVersion": "1.0",
  "ruleset": "gsom.studyplan.emba",
  "version": "0.1.0",
  "schemaRef": { "entity": "StudyPlan", "version": 1 },
  "settings": { "mode": "collect_all", "locale": "it", "maxSteps": 5000 },
  "constants": { "minCfu": 60 },
  "nodes": [],
  "edges": [],
  "ui": { "positions": {} }
}
```

| Campo | Significato |
| --- | --- |
| `ruleset` | Chiave del rule set, usata nell'URL `POST /v1/exec/{ruleset}` (minuscole, `.`, `-`, `_`) |
| `settings.mode` | `fail_fast` (default) o `collect_all`: cambia il comportamento di default su fallimento |
| `settings.locale` | Lingua di default dei messaggi |
| `settings.maxSteps` | Limite di passi per esecuzione (errore 422 se superato) |
| `constants` | Valori copiati in `$.vars` all'inizio di ogni esecuzione |
| `ui` | Solo per l'editor (posizioni, note): escluso dall'hash di versione |

## Context

Ogni espressione legge da uno scope JSON:

| Radice | Contenuto |
| --- | --- |
| `$.input` | L'oggetto ricevuto, in sola lettura |
| `$.vars` | Costanti e variabili scritte dai nodi `set` |
| `$.nodes.<id>` | `{ "outcome": "pass" \| "fail", "output": ... }` dei nodi già eseguiti |
| `$.meta` | `ruleset`, `version`, `referenceDate`, `requestId`, `locale` |
| `$.item` | L'elemento corrente dentro `where` / `select` |

Sintassi dei riferimenti: `.chiave`, `["chiave con spazi"]`, `[n]` (anche negativo), `[*]`
(espande un array: il risultato è una lista).

## Nodi

| Tipo | Campi | Porte in uscita |
| --- | --- | --- |
| `start` | | `next` |
| `condition` | `condition`, `onFail?`, `feedback?` | `pass` (obbligatoria), `fail` |
| `group` | `operator` (`and`/`or`/`not`), `evaluate` (`short_circuit`/`all`), `children`, `onFail?`, `feedback?` | `pass` (obbligatoria), `fail` |
| `set` | `assign: { nome: espressione }` scrive in `$.vars` | `next` |
| `switch` | `cases: [{ name, when }]`, il primo vero vince | ogni `name` + `default` (tutte obbligatorie) |
| `feedback` | `feedback`, `when?` | `next` |
| `end` | `outcome` (`valid`/`invalid`/`warning`), `output?: { chiave: espressione }` | nessuna |

Gli archi sono `{ "from": id, "to": id, "on": porta }` (`on` di default `next`). Il compiler
rifiuta: id duplicati, start mancante o multiplo, nessun end, porte inesistenti o collegate due
volte, porte obbligatorie scollegate, archi verso lo start, cicli. I nodi non raggiungibili
producono un warning.

I figli di un `group` sono espressioni oppure regole con feedback proprio:
`{ "rule": <espressione>, "feedback": { "fail": {...} } }`. Con `evaluate: "all"` ogni figlio
viene valutato (utile per raccogliere tutti gli errori); `not` vale NOT(AND(figli)).

## Fallimento, uscita ed esito

Politica `onFail` di un nodo `condition`/`group` che fallisce:

| Politica | Effetto | Conta come violazione |
| --- | --- | --- |
| `stop` | L'esecuzione termina subito con esito `invalid` (`exit.reason = "stop"`) | Sì |
| `continue` | Prosegue sulla porta `fail` se collegata, altrimenti su `pass` | Sì |
| `branch` | Segue la porta `fail` (obbligatoria): è solo controllo di flusso | No |

Default se `onFail` manca: `branch` se la porta `fail` è collegata, altrimenti `stop` in
`fail_fast` e `continue` in `collect_all`.

Esito finale: quello dell'`end` raggiunto; un `end` dichiarato `valid` diventa `invalid` se ci sono
violazioni o feedback con severità `error`, e `warning` se ci sono solo warning. Un errore di
valutazione (es. confronto tra tipi incompatibili) termina con esito `error`.

## Feedback

```json
{
  "code": "SP_CFU_MIN",
  "severity": "error",
  "path": "courses",
  "message": { "it": "Servono almeno {{vars.minCfu}} CFU", "en": "At least {{vars.minCfu}} ECTS" },
  "data": { "actual": { "ref": "$.vars.totalCfu" } }
}
```

Su `condition` e `group` (e sui figli dei gruppi) si definiscono `feedback.pass` e
`feedback.fail`. I segnaposto `{{...}}` sono riferimenti senza `$.`. Lingua: quella richiesta,
poi quella di default del rule set, poi la prima disponibile.

## Espressioni

Letterali JSON; liste di espressioni; `{"literal": <qualsiasi JSON>}` per oggetti letterali;
`{"ref": "$...."}`; operatori `{"op": ..., "left": ..., "right": ...}` (oppure `"args": [...]` o
`"arg"`); funzioni `{"fn": ..., "args": [...]}`.

| Operatori | Note |
| --- | --- |
| `==` `!=` | `null` e campo assente sono equivalenti |
| `<` `<=` `>` `>=` | `false` se un lato è assente; errore se i tipi non sono confrontabili |
| `between` | `right: [min, max]`, estremi inclusi |
| `date_before` `date_after` `date_between` | Confronto sulla parte data (ISO `YYYY-MM-DD...`) |
| `in` `not_in` | `right` lista letterale o riferimento a una lista |
| `contains` `starts_with` `ends_with` `regex` | `regex` richiede un pattern letterale |
| `exists` `is_null` `is_not_null` | `exists` distingue campo assente da `null` |
| `and` `or` `not` `if` | `if`: `args: [condizione, allora, altrimenti]` |
| `+` `-` `*` `/` `%` | `null` se un operando è assente |

| Funzioni | Note |
| --- | --- |
| `sum` `count` `min` `max` `avg` `any` `all` `distinct` `filter` `map` | Un argomento array; opzionali `where` (filtro) e `select` (proiezione) con `$.item` |
| `len` `lower` `upper` `trim` `coalesce` `round` `abs` `floor` | |
| `date` `today` `days_between` `age` | `today` e `age` usano `meta.referenceDate` (impostabile per richiesta) |

## Risultato di un'esecuzione

```json
{
  "requestId": "…",
  "ruleset": "gsom.studyplan.emba",
  "version": "0.1.0",
  "outcome": "valid | invalid | warning | error",
  "exit": { "nodeId": "endOk", "reason": "end | stop | error" },
  "feedback": [],
  "result": {},
  "path": ["start", "…"],
  "trace": null,
  "timing": { "engineUs": 212.4 }
}
```

`trace` è `null` con `options.trace = "none"`, la lista degli step con `summary`, e include output e
microsecondi per nodo con `full`.
