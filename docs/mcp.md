# MCP server · rules written by an AI assistant

Minos exposes an [MCP](https://modelcontextprotocol.io) (Model Context Protocol) server. From an MCP
client (Claude Desktop, Claude Code, other assistants) you describe in natural language what you
want to check; the assistant creates the entity with its schema and the rule set as a **draft**,
validates it, tries it on a few inputs, saves the test cases and gives you back the **Studio link**
to review it.

Publishing stays with you: the tools do not publish and do not move environments. Review the graph
in the Studio, simulate, fix and publish from *Versions* (the saved tests act as the gate).

## Connecting a client

The server is available in two ways.

**HTTP (Streamable HTTP) on the API's `/mcp`.** With `docker compose up` it is
`http://localhost:8000/mcp`. For Claude Code:

```bash
claude mcp add --transport http minos http://localhost:8000/mcp
```

Clients that accept an MCP URL just need the same address. As DNS rebinding protection the
endpoint accepts only requests with host `localhost`, `127.0.0.1` or `[::1]`.

**stdio**, for clients that start the server as a command (for example Claude Desktop, in
`claude_desktop_config.json`). It needs the repository and [uv](https://docs.astral.sh/uv/); the
command talks to the API given by `MINOS_API_URL`:

```json
{
  "mcpServers": {
    "minos": {
      "command": "uv",
      "args": ["--directory", "/path/to/minos/backend", "run", "python", "-m", "minos.mcp"],
      "env": {
        "MINOS_API_URL": "http://localhost:8000",
        "MINOS_STUDIO_URL": "http://localhost:8080"
      }
    }
  }
}
```

| Variable | Default | Meaning |
| --- | --- | --- |
| `MINOS_API_URL` | `http://localhost:8000` | Minos API (stdio only) |
| `MINOS_STUDIO_URL` | `http://localhost:8080` | Studio address in the returned links (stdio and `/mcp`) |
| `MINOS_API_KEY` | — | Key with scope `manage`, if the installation requires API keys (stdio only) |

With `MINOS_REQUIRE_AUTH=true`, on `/mcp` the client must send its own key
(`Authorization: Bearer mns_...` or `X-Api-Key`): the server forwards it to the Management API, so
the same scopes apply. Without a key the tools answer 401.

## Tools

| Tool | What it does |
| --- | --- |
| `guide` | Workflow, full example and RGD format reference (read it first) |
| `list_workspaces`, `create_workspace` | Existing workspaces; create a new one |
| `list_entities`, `get_entity` | Entities and their JSON Schema |
| `create_entity` | New entity with the schema derived from sample objects (or a JSON Schema, which can use other entities as field types with `{"$ref": "entity:<key>"}`) |
| `update_entity_schema` | New schema version (for example one more field) |
| `list_rulesets`, `get_ruleset` | Rule sets, published versions, environments, draft and tests |
| `create_ruleset` | New rule set with the graph as a draft; returns the validation and the link |
| `update_ruleset` | Replaces the draft (with a concurrent-edit check); validation, tests, link. Pass `lock_version` (from `get_ruleset`) so that a save made meanwhile is not overwritten |
| `validate_ruleset` | Compiles the draft against the schema: problems and warnings |
| `simulate_ruleset` | Runs the draft on an input: outcome, messages, result, path |
| `add_test`, `run_tests` | Saves test cases (the publication gate) and runs them on the draft |

Every write returns `studioUrl`, for example
`http://localhost:8080/w/shop/rulesets/shop.order.basic`.

## Example

> In the *shop* workspace I want to validate orders: at least one line, a total (quantity × price)
> of at least 10 euros, and a warning above 5,000 euros. Here is a sample order: …

The assistant reads `guide`, creates the `Order` entity from the sample, writes the rule set with
the thresholds as constants, fixes it until validation passes, simulates a valid order and an
empty one, saves the two cases as tests and replies with a summary and the Studio link.

The server is a thin layer over the Management API (`minos.mcp`): every API rule applies
(validation, optimistic draft locking, audit with the author of the change).
