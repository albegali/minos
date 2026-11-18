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
| `MINOS_REQUIRE_AUTH` | `false` | `true` to require authentication: users sign in (e-mail and password), machines use API keys; any value other than `true/false/1/0/yes/no/on/off` stops the start-up |
| `MINOS_ALLOW_SIGNUP` | `false` | `true` lets anyone who reaches the Studio register a new organization and become its owner |
| `MINOS_CORS_ORIGINS` | — | Allowed browser origins, comma-separated |
| `MINOS_RULESETS_DIR` | — | RGD files served as workspace `local`, environment `prod` |
| `MINOS_POLL_INTERVAL_S` | `30` | Periodic alias check (safety net for lost NOTIFYs), at least 1 |
| `MINOS_EXEC_TIME_LIMIT_MS` | `1000` | Wall-clock budget of one execution, sub rule sets included (`422` beyond it) |
| `MINOS_PUBLISH_REQUIRES_TESTS` | `false` | `true` to refuse publishing a rule set without tests (recommended in production) |
| `MINOS_ALLOWED_HOSTS` | (local names) | Open installations (no API keys) answer only to `localhost`, `127.0.0.1`, `::1` and these comma-separated names (`421` otherwise; `*` for any), against DNS rebinding |
| `MINOS_EXAMPLES_DIR` | the repo's `examples/` | Examples loaded by `minos.cli seed-examples` |
| `MINOS_SEED_EXAMPLES` | `true` only in the Docker image | Loads the examples on the container's first start |
| `MINOS_STUDIO_URL` | `http://localhost:8080` | Studio address in the links returned by the MCP server and in invitation links |
| `MINOS_SESSION_HOURS` | `12` | How long a Studio sign-in lasts |
| `MINOS_INVITATION_DAYS` | `7` | How long an invitation link can be used |
| `MINOS_AUDIT_RETENTION_DAYS` | `90` | `minos.cli prune-audit` deletes draft-save events older than this |

With neither a database nor a directory, `minos.api.app:app` serves the repo's examples: this is
the demo mode used by Minos Studio. With the database, `minos.api.app:app` also exposes the MCP
server on `/mcp` (see [`mcp.md`](mcp.md)).

`GET /v1/info` (always public) describes the installation:
`{"name", "version", "authRequired", "management", "database", "signup"}`. The Studio uses it to
decide whether to ask for a sign-in, whether to offer registration and whether to open the demo.

## Authentication (optional)

By default the installation is **open**: no key required (`compose.yaml` publishes the ports on
`127.0.0.1` only). With `MINOS_REQUIRE_AUTH=true` every call needs `Authorization: Bearer <token>`
(or `X-Api-Key`), where the token is either an **API key** (machines) or a **session** of a
signed-in user (people, the Studio). See ADR 0005 and ADR 0008.

### API keys (machines)

| Scope | Reach | Allows |
| --- | --- | --- |
| `admin` | global | everything: organizations, workspaces, admin keys, all audit |
| `manage` | one workspace | the workspace's Management API (admin role in it) |
| `exec` | one workspace | the workspace's Execution API |

Key names are unique among the active keys of a workspace (`409` otherwise), and every key
records who created it (`createdBy`).

### Users, organizations, roles (people)

Organizations are tenants: each workspace belongs to one (the pre-existing ones, and those created
by admin keys without naming one, to `default`). A user has one password and any number of e-mail
addresses, each of which signs in; a session works in one organization at a time.

Workspace slugs are unique **within an organization** (two organizations can both have `rules`),
and URLs carry only the slug: the organization comes from the caller.

| Caller | Organization of `/v1/workspaces/{ws}/...` and `/v1/exec/{ws}/...` |
| --- | --- |
| Signed-in user | the one chosen for the session |
| `manage` / `exec` key | the one of the key's workspace |
| `admin` key, open installation | `X-Minos-Organization: <slug>` if sent, else `default` |

`GET /v1/workspaces` with an admin key and no header lists every organization's workspaces, each
with its `organization`. `GET /v1/deployments` names workspaces by slug in `default` and
`<organization>/<slug>` elsewhere. The MCP server forwards `X-Minos-Organization` too.

| Role | Where | Allows |
| --- | --- | --- |
| `owner` | organization | everything in it; manages owners; the last one cannot leave |
| `admin` | organization | members, invitations, workspaces; admin of every workspace |
| `member` | organization | only the workspaces where they have a role |
| `viewer` | workspace | read, validate, simulate, run tests, diff, export |
| `author` | workspace | + entities, schemas, rule sets, drafts, tests, import |
| `publisher` | workspace | + publish, archive, environments (`prod` included) |
| `admin` | workspace | + API keys, members, audit |

| Method and path | Description |
| --- | --- |
| `POST /auth/login` | `{"email", "password", "organization"?}` → `{token, user, organization, organizations, expiresAt}`; with several organizations and none named, `organization` is `null`: choose one next. `401` wrong credentials, `429` too many failures for the address |
| `POST /auth/signup` | Only with `MINOS_ALLOW_SIGNUP=true` (`403` otherwise). `{"organization": {"slug", "name"}}` plus, when not signed in, `{"email", "password"}` of an existing account or `{"name", "email", "password"}` for a new one; signed in, the current account owns it. Creates the organization with the caller as owner and returns a session in it (`409` slug taken) |
| `POST /auth/organization` | `{"organization"}`: move the session to another of the user's organizations |
| `GET /auth/me` | The signed-in user and their organizations, or the API key (`kind`, `name`, `scopes`) |
| `PUT /auth/password` | `{"current", "new"}` (at least 12 characters) |
| `POST /auth/logout` | Ends the session |
| `GET /auth/invitations/{token}` | Public: organization, address, role, whether the address has an account |
| `POST /auth/invitations/{token}/accept` | Signed in: the address joins the current account. Otherwise `{"password"}` of the account using the address, or `{"name", "password"}` for a new one. Returns a session in that organization |
| `GET/POST /organizations` | Your organizations (users) or all (admin keys); create (admin keys; users through `/auth/signup`) |
| `GET /organizations/{org}/members` | Members with all their addresses and workspace roles |
| `PUT/DELETE /organizations/{org}/members/{userId}` | `{"role"}` / remove (owners and admins; anyone can remove themselves) |
| `GET/POST /organizations/{org}/invitations` · `DELETE .../{id}` | Pending invitations; `{"email", "role", "workspaces": [{"workspace", "role"}]}` returns the link (`url`, `token`) once: Minos sends no e-mail |
| `GET /organizations/{org}/audit` | Audit of the organization and its workspaces (owners, admins) |
| `GET /admin/audit?scope=all\|global` | Whole audit, or only events of no organization (admin keys) |
| `GET /workspaces/{ws}/members` · `PUT/DELETE .../members/{userId}` | Who can open the workspace; give or take a member's role (workspace admins) |

The first organization and its owner come from the command line:

```bash
MINOS_DATABASE_URL=... uv run python -m minos.cli migrate
MINOS_DATABASE_URL=... uv run python -m minos.cli create-organization --slug gsom --name "GSoM"
MINOS_DATABASE_URL=... uv run python -m minos.cli create-user --email ada@example.org \
    --name "Ada" --organization gsom --role owner      # asks the password (or MINOS_PASSWORD)
```

and the first admin key too:

```bash
MINOS_DATABASE_URL=... uv run python -m minos.cli create-admin-key --name ops
MINOS_DATABASE_URL=... uv run python -m minos.cli list-admin-keys
MINOS_DATABASE_URL=... uv run python -m minos.cli revoke-key <id>   # any key, admin or workspace
MINOS_DATABASE_URL=... uv run python -m minos.cli prune-audit       # audit retention (draft saves)
```

### Audit

Every change records the actor (`user:<e-mail>`, `apikey:<name>`, `cli`), the channel `via`
(`studio`, `api`, `mcp`, `cli`: the Studio and the MCP server send `X-Minos-Via`), the
organization and the workspace. Listings (`/workspaces/{ws}/audit`, `/organizations/{org}/audit`,
`/admin/audit`) take `action` (exact, or a family ending with a dot: `alias.`), `target` (prefix),
`actor`, `via`, `since`, `until` (ISO dates or date-times), `limit` (≤ 1000) and `cursor`, and
return `{"items": [...], "next": <cursor or null>}`, newest first. Consecutive draft saves of the
same actor through the same channel within 15 minutes are one event (`detail.saves`).

Request bodies over 10 MB get `413` on every endpoint (the execution input is limited to 1 MB).
`POST .../import` accepts only `Content-Type: application/json`. API keys that do not have the
shape Minos issues (`mns_` plus 43 characters) are refused without a database lookup.

## Management API

All paths under `/v1`. `{ws}` is the workspace slug, `{rs}` the rule set key.

| Method and path | Description |
| --- | --- |
| `GET/POST /workspaces` | List the workspaces you can open, with `organization` and your `role`; create (`{"slug", "name", "organization"?}`: organization owners and admins, admin keys) |
| `GET/POST /workspaces/{ws}/api-keys` · `DELETE .../api-keys/{id}` | Workspace keys; the plaintext key is returned only on creation |
| `GET/POST /admin/api-keys` · `DELETE .../api-keys/{id}` | Global admin keys (admin): list, create, revoke |
| `GET /workspaces/{ws}/audit` | Change log (see *Audit* above) |
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
| `GET/POST .../rulesets/{rs}/tests` · `PUT/DELETE .../tests/{name}` · `POST .../tests/run` | The rule set's test cases; `PUT` creates or replaces one. Test inputs are checked against the entity schema, as executions are |
| `POST .../rulesets/{rs}/publish` | `{"bump": "major|minor|patch", "notes"?, "promoteTo"?}`; fails with `422` if the draft does not compile or a test does not pass (or there are none, with `MINOS_PUBLISH_REQUIRES_TESTS`). A draft identical to the latest version publishes nothing: `200` with that version and `created: false` (promoted if asked), so retries are harmless |
| `POST .../rulesets/{rs}/versions/{v}/archive` | Withdraws a version: it can no longer be promoted nor executed by number; `409` while an environment points at it |
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
