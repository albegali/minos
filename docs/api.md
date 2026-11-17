# API · reference (F1)

Two planes, deployable separately:

| App | Uvicorn target | Use |
| --- | --- | --- |
| Execution API | `minos.api.app:execution_app` | Third-party systems; in-memory hot path |
| Management API | `minos.api.app:management_app` | Minos Studio, CI, administrators |
| Both (development) | `minos.api.app:app` | A single process |

Configuration through environment variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `MINOS_DATABASE_URL` | — | `postgresql+asyncpg://user:pass@host:5432/db` |
| `MINOS_REQUIRE_AUTH` | `false` | `true` to require API keys; any value other than `true/false/1/0/yes/no/on/off` stops the start-up |
| `MINOS_CORS_ORIGINS` | — | Allowed browser origins, comma-separated |
| `MINOS_RULESETS_DIR` | — | RGD files served as workspace `local`, environment `prod` |
| `MINOS_POLL_INTERVAL_S` | `30` | Periodic alias check (safety net for lost NOTIFYs), at least 1 |
| `MINOS_EXEC_TIME_LIMIT_MS` | `1000` | Wall-clock budget of one execution, sub rule sets included (`422` beyond it) |
| `MINOS_EXAMPLES_DIR` | the repo's `examples/` | Examples loaded by `minos.cli seed-examples` |
| `MINOS_SEED_EXAMPLES` | `true` only in the Docker image | Loads the examples on the container's first start |
| `MINOS_STUDIO_URL` | `http://localhost:8080` | Studio address in the links returned by the MCP server |

With neither a database nor a directory, `minos.api.app:app` serves the repo's examples: this is
the demo mode used by Minos Studio. With the database, `minos.api.app:app` also exposes the MCP
server on `/mcp` (see [`mcp.md`](mcp.md)).

`GET /v1/info` (always public) describes the installation:
`{"name", "version", "authRequired", "management", "database"}`. The Studio uses it to decide
whether to ask for a key and whether to open the demo.

## Authentication (optional)

By default the installation is **open**: no key required. With `MINOS_REQUIRE_AUTH=true` you need
`Authorization: Bearer mns_...` or `X-Api-Key: mns_...`, with these scopes (ADR 0005):

| Scope | Reach | Allows |
| --- | --- | --- |
| `admin` | global | everything, including creating workspaces and admin keys |
| `manage` | one workspace | the workspace's Management API |
| `exec` | one workspace | the workspace's Execution API |

The first admin key is created from the command line:

```bash
MINOS_DATABASE_URL=... uv run python -m minos.cli migrate
```

```bash
MINOS_DATABASE_URL=... uv run python -m minos.cli create-admin-key --name ops
MINOS_DATABASE_URL=... uv run python -m minos.cli list-admin-keys
MINOS_DATABASE_URL=... uv run python -m minos.cli revoke-key <id>   # any key, admin or workspace
```

## Ready-made examples

```bash
MINOS_DATABASE_URL=... uv run python -m minos.cli seed-examples
```

Creates the `esempi` workspace with every example in the repo (Aurora study plan, e-commerce
order, loan, enrollment): entities with the schema derived from the sample inputs, or written in
`entities/<key>.json` (these can use other entities as field types), rule sets with their tests,
version `0.1.0` published (the tests act as the gate) and moved to `prod`. If the workspace already
exists it only adds the examples it lacks: existing entities and rule sets (by key) are left
alone, so changes made in the Studio are kept. `--workspace` picks another
name, `--dir` another folder (`rulesets/`, `inputs/`, `tests/`, optionally `entities/`). The Docker image runs it on every
start (`MINOS_SEED_EXAMPLES=false` to start empty).

Errors are `application/problem+json` (`status`, `title`, `detail` plus specific fields).

### References allowed in schemas

A schema is self-contained: `$ref` may point inside it (`#/$defs/...`) or at another entity
(`entity:Key`, see below). Any other reference (`http://...`, `file://...`, `other.json`) is
rejected with `422`, and the server never downloads schemas.

### Entities made of other entities

When the input combines several objects (a student, their study plan, the program and its
courses), create one entity per kind of object, then one for the whole input that uses them as
field types:

```json
{
  "type": "object",
  "properties": {
    "student": { "$ref": "entity:Student" },
    "plan": { "$ref": "entity:StudyPlan" },
    "program": { "$ref": "entity:Program" }
  },
  "required": ["student", "plan", "program"]
}
```

`Program` can itself hold `"courses": {"type": "array", "items": {"$ref": "entity:Course"}}`.
A rule set on this entity reads every part directly (`$.input.student.birthDate`,
`$.input.program.courses[*].cfu`); no `subruleset` is needed.

- When the schema is saved, `entity:Course` is pinned to Course's latest version and stored as
  `entity:Course@2`. A version written explicitly is kept. A new version of Course does not change
  the schemas that use it: `references[].latest` shows that it exists, and saving the schema again
  with unpinned references moves them forward (*Update references* in the Studio).
- Only `title` and `description` may sit next to a reference (`422` otherwise), as well as for an
  unknown entity or version.
- `resolved` embeds the referenced versions under `$defs["entity:<key>@<version>"]`. Execution
  validates the input against it and the Swagger shows it. Bundles carry the referenced entities
  too, so a bundle imports where they do not exist and the imported entity keeps its references.

## Execution API

| Method and path | Description |
| --- | --- |
| `POST /v1/exec/{ws}/{ruleset}` | Runs the `prod` alias (the version in force on the reference date) |
| `POST /v1/exec/{ws}/{ruleset}@{env}` | Runs the `env` alias (`test`, `dev`, ...) |
| `POST /v1/exec/{ws}/{ruleset}/versions/{semver}` | Runs a pinned version (loaded on the first request, then cached) |
| `GET /v1/health` · `GET /v1/ready` | Probes; `ready` after the initial load |
| `GET /v1/deployments` | Aliases loaded in the worker, with version and hash (admin key) |
| `GET /v1/exec/openapi.json[?workspace=<ws>]` | OpenAPI 3.1 of the deployed rule sets (see below) |
| `GET /v1/exec/docs[?workspace=<ws>]` | Swagger UI on the same document |

### Rule set Swagger

FastAPI's `/openapi.json` and `/docs` describe the platform: a single execution endpoint with a
free-form `input`. `/v1/exec/openapi.json` instead describes what is deployed: one operation per
rule set and environment (`/v1/exec/{ws}/{rs}` for `prod`, `/v1/exec/{ws}/{rs}@{env}` for the
others), with the entity schema as the request body, the version in force and the schedule of
planned versions, and the feedback codes declared by the graph.

The document is generated from the worker's in-memory registry, so it updates itself when a version
is published to an environment (`promoteTo`) or an alias changes: no extra steps. A version that is
published but not moved to any environment does not appear (it can still be run through
`/versions/{semver}`).

With `MINOS_REQUIRE_AUTH=true` the document lists only the rule sets the key can run (all of them
for an admin key, those of its workspace for an `exec` key, none without a key). In the Swagger UI:
*Authorize* with the key, then reload the page. The key stays in the browser and is also sent with
the document request.

Body: `{"input": {...}, "options": {"trace": "none|summary|full", "locale": "it",
"referenceDate": "2027-09-20", "validateSchema": true}}`.

- `referenceDate` (default: today, UTC) is the rules' "reference" date: it feeds `today()` and
  `age()` and picks the version when the environment has scheduled versions.
- `validateSchema: false` skips the input check against the entity schema: with API keys on, only
  an `admin` or `manage` key may ask for it (`403` otherwise). Values of an unexpected type then
  end with outcome `error`.
- `200` with the outcome in the body (`valid`, `invalid`, `warning`); `422` if execution fails or
  exceeds `maxSteps` or the time limit; `400` if the input does not match the entity schema (`errors` list with JSON
  pointers); `401`/`403` for keys; `404` if the rule set or the alias is not deployed.
- Headers: `X-Ruleset-Version`, `X-Ruleset-Hash`, `X-Request-Id` (echo of the one received),
  `Server-Timing: engine;dur=<ms>`.

## Management API

All paths under `/v1`. `{ws}` is the workspace slug, `{rs}` the rule set key.

| Method and path | Description |
| --- | --- |
| `GET/POST /workspaces` | List (filtered by key) and create (admin) |
| `GET/POST /workspaces/{ws}/api-keys` · `DELETE .../api-keys/{id}` | Workspace keys; the plaintext key is returned only on creation |
| `GET/POST /admin/api-keys` · `DELETE .../api-keys/{id}` | Global admin keys (admin): list, create, revoke |
| `GET /workspaces/{ws}/audit?limit=100` | Change log |
| `POST /schemas/infer` | `{"samples": [...], "title"?}` → JSON Schema 2020-12, without saving it |
| `GET/POST /workspaces/{ws}/entities` | Entities |
| `GET .../entities/{entity}` | One entity with `usedBy`: the entities whose latest schema references it |
| `GET/POST .../entities/{entity}/schemas` | Schema versions: `{"schema": {...}}` or `{"samples": [...]}`; a schema identical to the latest does not create a version. In a schema, `{"$ref": "entity:<key>"}` makes another entity the type of a field (see below) |
| `GET .../entities/{entity}/schemas/{version}` | One version: `schema` (as written), `resolved` (standalone, what rules read) and `references` (`{entity, version, latest}`) |
| `GET/POST /workspaces/{ws}/rulesets` | Rule sets: `{"key", "name", "entity", "graph"?}`; the draft starts from the given graph or from start → end |
| `GET .../rulesets/{rs}` | Metadata, entity, latest version, `aliases` (version in force today per environment) and `schedule` (full schedule) |
| `GET/PUT .../rulesets/{rs}/draft` | Draft with `ETag`; `PUT` with `If-Match` for optimistic locking (`412` if changed); optional `schemaVersion` |
| `POST .../rulesets/{rs}/validate` | Compiles and type-checks: `{"valid", "issues": [{"where", "message"}], "warnings"}` |
| `POST .../rulesets/{rs}/simulate` | Runs the draft (`full` trace by default) |
| `GET/POST .../rulesets/{rs}/tests` · `DELETE .../tests/{name}` · `POST .../tests/run` | The rule set's test cases |
| `POST .../rulesets/{rs}/publish` | `{"bump": "major|minor|patch", "notes"?, "promoteTo"?}`; fails with `422` if the draft does not compile or a test does not pass |
| `GET .../rulesets/{rs}/versions[/{semver}]` | Published (immutable) versions |
| `GET .../rulesets/{rs}/aliases` | Schedule per environment: `{"prod": [{"version": "1.0.0", "effectiveFrom": null}, {"version": "2.0.0", "effectiveFrom": "2027-08-01"}]}` |
| `PUT .../aliases/{env}` | `{"version": "2.0.0", "effectiveFrom"?: "2027-08-01"}`: without a date it replaces the undated entry; with a date it adds or updates that entry. Workers update through NOTIFY |
| `DELETE .../aliases/{env}` | Removes the environment; `?effectiveFrom=YYYY-MM-DD` removes only that entry, `?effectiveFrom=always` the undated one |
| `GET .../rulesets/{rs}/diff?from=<v>&to=<v\|draft>` | Added, removed and changed nodes (field by field), edges, settings and constants; canvas positions are ignored |
| `GET .../rulesets/{rs}/export[?version=<v>]` | `minos-bundle/1` JSON bundle: rule set, entity schema, tests, dependencies (the draft if `version` is missing) |
| `POST /workspaces/{ws}/import` | Imports a bundle: creates or updates entity, schema (if different), rule set (as a draft, never published automatically) and tests (replaced by name); the entities the schema references (`entities`) are matched to identical versions or added as new ones, keeping the references; the sub rule sets listed in `dependencies` must be imported and published first |

### Test cases

```json
{
  "name": "invalid plan",
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

Every key in `expected` is optional: `feedbackCodes` compares the set of codes (with repetitions,
order ignored), `result` is a subset comparison.
