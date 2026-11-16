# API · riferimento (F1)

Due piani, deployabili separatamente:

| App | Uvicorn target | Uso |
| --- | --- | --- |
| Execution API | `minos.api.app:execution_app` | Sistemi terzi; percorso caldo in memoria |
| Management API | `minos.api.app:management_app` | Minos Studio, CI, amministratori |
| Entrambe (sviluppo) | `minos.api.app:app` | Un solo processo |

Configurazione da variabili d'ambiente:

| Variabile | Default | Significato |
| --- | --- | --- |
| `MINOS_DATABASE_URL` | — | `postgresql+asyncpg://user:pass@host:5432/db` |
| `MINOS_REQUIRE_AUTH` | `true` | `false` solo in sviluppo locale |
| `MINOS_RULESETS_DIR` | — | File RGD serviti come workspace `local`, ambiente `prod` |
| `MINOS_POLL_INTERVAL_S` | `30` | Controllo periodico degli alias (rete di sicurezza per NOTIFY persi) |

Senza database né directory, `minos.api.app:app` serve gli esempi del repo senza autenticazione:
è la modalità demo usata da Minos Studio.

## Autenticazione

`Authorization: Bearer mns_...` oppure `X-Api-Key: mns_...`. Scope (ADR 0005):

| Scope | Ambito | Permette |
| --- | --- | --- |
| `admin` | globale | tutto, compresa la creazione di workspace e chiavi admin |
| `manage` | un workspace | Management API del workspace |
| `exec` | un workspace | Execution API del workspace |

La prima chiave admin si crea da riga di comando:

```bash
MINOS_DATABASE_URL=... uv run python -m minos.cli migrate
```

```bash
MINOS_DATABASE_URL=... uv run python -m minos.cli create-admin-key --name ops
```

Gli errori sono `application/problem+json` (`status`, `title`, `detail` più campi specifici).

## Execution API

| Metodo e path | Descrizione |
| --- | --- |
| `POST /v1/exec/{ws}/{ruleset}` | Esegue l'alias `prod` |
| `POST /v1/exec/{ws}/{ruleset}@{env}` | Esegue l'alias `env` (`test`, `dev`, ...) |
| `POST /v1/exec/{ws}/{ruleset}/versions/{semver}` | Esegue una versione fissa (caricata alla prima richiesta, poi in cache) |
| `GET /v1/health` · `GET /v1/ready` | Probe; `ready` dopo il caricamento iniziale |
| `GET /v1/deployments` | Alias caricati nel worker, con versione e hash (chiave admin) |

Corpo: `{"input": {...}, "options": {"trace": "none|summary|full", "locale": "it",
"referenceDate": "2027-09-20", "validateSchema": true}}`.

- `200` con l'esito nel corpo (`valid`, `invalid`, `warning`); `422` se l'esecuzione va in errore o
  supera `maxSteps`; `400` se l'input non rispetta lo schema dell'entità (lista `errors` con JSON
  pointer); `401`/`403` per le chiavi; `404` se il rule set o l'alias non sono deployati.
- Header: `X-Ruleset-Version`, `X-Ruleset-Hash`, `X-Request-Id` (eco di quello ricevuto),
  `Server-Timing: engine;dur=<ms>`.

## Management API

Tutti i path sotto `/v1`. `{ws}` è lo slug del workspace, `{rs}` la chiave del rule set.

| Metodo e path | Descrizione |
| --- | --- |
| `GET/POST /workspaces` | Elenco (filtrato per chiave) e creazione (admin) |
| `GET/POST /workspaces/{ws}/api-keys` · `DELETE .../api-keys/{id}` | Chiavi del workspace; la chiave in chiaro è restituita solo alla creazione |
| `POST /admin/api-keys` | Chiave admin globale |
| `GET /workspaces/{ws}/audit?limit=100` | Registro delle modifiche |
| `POST /schemas/infer` | `{"samples": [...], "title"?}` → JSON Schema 2020-12, senza salvarlo |
| `GET/POST /workspaces/{ws}/entities` | Entità |
| `GET/POST .../entities/{entity}/schemas` | Versioni dello schema: `{"schema": {...}}` oppure `{"samples": [...]}`; uno schema identico all'ultimo non crea una versione |
| `GET .../entities/{entity}/schemas/{version}` | Una versione con il documento |
| `GET/POST /workspaces/{ws}/rulesets` | Rule set: `{"key", "name", "entity", "graph"?}`; il draft parte dal grafo dato o da start → end |
| `GET .../rulesets/{rs}` | Metadati, ultima versione, alias |
| `GET/PUT .../rulesets/{rs}/draft` | Draft con `ETag`; `PUT` con `If-Match` per il lock ottimistico (`412` se cambiato); `schemaVersion` opzionale |
| `POST .../rulesets/{rs}/validate` | Compila e fa il type-check: `{"valid", "issues": [{"where", "message"}], "warnings"}` |
| `POST .../rulesets/{rs}/simulate` | Esegue il draft (trace `full` di default) |
| `GET/POST .../rulesets/{rs}/tests` · `DELETE .../tests/{name}` · `POST .../tests/run` | Test case del rule set |
| `POST .../rulesets/{rs}/publish` | `{"bump": "major|minor|patch", "notes"?, "promoteTo"?}`; fallisce con `422` se il draft non compila o un test non passa |
| `GET .../rulesets/{rs}/versions[/{semver}]` | Versioni pubblicate (immutabili) |
| `GET .../rulesets/{rs}/aliases` · `PUT/DELETE .../aliases/{env}` | Alias per ambiente: `{"version": "1.2.0"}`; i worker si aggiornano via NOTIFY |

### Test case

```json
{
  "name": "piano non valido",
  "input": { "...": "..." },
  "referenceDate": "2027-09-20",
  "expected": {
    "outcome": "invalid",
    "exitNodeId": "endOk",
    "feedbackCodes": ["SP_CFU_MIN", "SP_FIN_LIMIT"],
    "result": { "totalCfu": 40 }
  }
}
```

Tutte le chiavi di `expected` sono facoltative: `feedbackCodes` confronta l'insieme dei codici
(con ripetizioni, ordine ignorato), `result` è un confronto per sottoinsieme.
