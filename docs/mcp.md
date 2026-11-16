# Server MCP · regole scritte da un assistente AI

Minos espone un server [MCP](https://modelcontextprotocol.io) (Model Context Protocol). Da un
client MCP (Claude Desktop, Claude Code, altri assistenti) descrivi in linguaggio naturale cosa
vuoi controllare; l'assistente crea l'entità con il suo schema e il rule set come **draft**, lo
valida, lo prova su qualche input, salva i casi di test e ti restituisce il **link allo Studio**
per rivederlo.

La pubblicazione resta a te: i tool non pubblicano e non spostano ambienti. Rivedi il grafo nello
Studio, simula, correggi e pubblica da *Versioni* (i test salvati fanno da gate).

## Collegare un client

Il server è disponibile in due modi.

**HTTP (Streamable HTTP) su `/mcp` dell'API.** Con `docker compose up` è
`http://localhost:8000/mcp`. Per Claude Code:

```bash
claude mcp add --transport http minos http://localhost:8000/mcp
```

Per i client che accettano un URL MCP, basta indicare lo stesso indirizzo. Per protezione da DNS
rebinding l'endpoint accetta solo richieste con host `localhost`, `127.0.0.1` o `[::1]`.

**stdio**, per i client che avviano il server come comando (per esempio Claude Desktop, in
`claude_desktop_config.json`). Serve il repository con [uv](https://docs.astral.sh/uv/); il comando
parla con l'API indicata da `MINOS_API_URL`:

```json
{
  "mcpServers": {
    "minos": {
      "command": "uv",
      "args": ["--directory", "/percorso/di/minos/backend", "run", "python", "-m", "minos.mcp"],
      "env": {
        "MINOS_API_URL": "http://localhost:8000",
        "MINOS_STUDIO_URL": "http://localhost:8080"
      }
    }
  }
}
```

| Variabile | Default | Significato |
| --- | --- | --- |
| `MINOS_API_URL` | `http://localhost:8000` | API di Minos (solo stdio) |
| `MINOS_STUDIO_URL` | `http://localhost:8080` | Indirizzo dello Studio nei link restituiti (stdio e `/mcp`) |
| `MINOS_API_KEY` | — | Chiave con scope `manage`, se l'installazione richiede le API key (solo stdio) |

Con `MINOS_REQUIRE_AUTH=true`, su `/mcp` il client deve inviare la propria chiave
(`Authorization: Bearer mns_...` o `X-Api-Key`): il server la inoltra alla Management API, quindi
valgono gli stessi scope. Senza chiave i tool rispondono 401.

## Tool

| Tool | Cosa fa |
| --- | --- |
| `guide` | Flusso di lavoro, esempio completo e riferimento del formato RGD (da leggere per primo) |
| `list_workspaces`, `create_workspace` | Workspace esistenti; crearne uno nuovo |
| `list_entities`, `get_entity` | Entità e loro JSON Schema |
| `create_entity` | Nuova entità con lo schema ricavato da oggetti di esempio (o un JSON Schema) |
| `update_entity_schema` | Nuova versione dello schema (per esempio un campo in più) |
| `list_rulesets`, `get_ruleset` | Rule set, versioni pubblicate, ambienti, draft e test |
| `create_ruleset` | Nuovo rule set con il grafo come draft; restituisce la validazione e il link |
| `update_ruleset` | Sostituisce il draft (con controllo di modifiche concorrenti); validazione, test, link |
| `validate_ruleset` | Compila il draft contro lo schema: problemi e avvisi |
| `simulate_ruleset` | Esegue il draft su un input: esito, messaggi, risultato, percorso |
| `add_test`, `run_tests` | Salva casi di test (gate della pubblicazione) e li esegue sul draft |

Ogni scrittura restituisce `studioUrl`, per esempio
`http://localhost:8080/w/shop/rulesets/shop.order.basic`.

## Esempio

> Nel workspace *shop* voglio validare gli ordini: almeno una riga, totale (quantità × prezzo)
> di almeno 10 euro, e un avviso sopra i 5.000 euro. Ecco un ordine di esempio: …

L'assistente legge `guide`, crea l'entità `Order` dall'esempio, scrive il rule set con le soglie
nelle costanti, corregge finché la validazione passa, simula un ordine valido e uno vuoto, salva
i due casi come test e risponde con il riepilogo e il link allo Studio.

Il server è un sottile strato sulla Management API (`minos.mcp`): vale qualunque regola dell'API
(validazione, lock ottimistico dei draft, audit con l'autore della modifica).
