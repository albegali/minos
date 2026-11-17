# Improvements

The open issues and weaknesses of Minos, from a static analysis and a code review of the
whole repository (backend, Studio, deployment) done on 2026-11-17 on branch
`feat/entity-references` (commit `d219f9d`). Keep this file current: when an item is fixed, set
its status to `done` and add the PR; when a new problem is found, add a row with the next free
ID of its area.

- **Severity**: `high` breaks results, loses data or exposes the installation; `medium` is a
  real defect or gap with a workaround; `low` is minor or cosmetic.
- **Status**: `open`, `in progress`, `done (#PR)`, `wontfix (reason)`.
- **Checked**: `run` = reproduced by running code; `read` = unambiguous from the code;
  `plausible` = the code allows it, not reproduced.

Line numbers refer to the commit above and drift as the code changes.

## Summary

| Area | High | Medium | Low |
| --- | --- | --- | --- |
| [Security](#security) | 3 | 9 | 3 |
| [Engine](#engine) | 3 | 10 | 8 |
| [Control plane](#control-plane) | 4 | 8 | 6 |
| [API and MCP](#api-and-mcp) | 1 | 5 | 7 |
| [Studio](#studio) | 4 | 16 | 9 |
| [Functional gaps](#functional-gaps) | – | 14 | 6 |
| [Code quality](#code-quality) | – | 5 | 6 |

Suggested first batch, by risk: SEC-01, SEC-02, SEC-03, ENG-01, ENG-02, ENG-03, CTL-01, CTL-02,
CTL-03, CTL-04, API-01, UI-01, UI-02, UI-03, UI-04.

## Security

| ID | Sev | Status | Checked | Issue | Where |
| --- | --- | --- | --- | --- | --- |
| SEC-01 | high | done (fix/improvements) | run | **SSRF and local file read through remote `$ref`.** `check_schema` only validates against the meta-schema, so `{"$ref": "http://169.254.169.254/…"}` or `file:///…` is accepted; jsonschema-rs fetches it whenever a validator is built (every deployment load, promotion, version load), synchronously on the event loop. Disable the retriever (or allow only `#…` and `entity:` refs) and reject external refs at save time. | `schema/validate.py:38`, `api/registry.py:83`, `control/service.py:156` |
| SEC-02 | high | done (fix/improvements) | run | **Response/memory amplification with `validateSchema:false`.** Any caller can skip input validation; error messages echo values unbounded. A 1 KB request (`unitPrice:"x"`, `quantity:2e8` on `shop.order`) produced a 200 MB response and ~790 MB RSS. Restrict the opt-out to manage scope and truncate values in messages. | `api/execution.py:111`, `engine/expressions.py:176-186` |
| SEC-03 | high | done (fix/improvements) | run | **Admin keys cannot be revoked.** `revoke_api_client` requires `workspace_id == ws.id`, admin keys have `NULL`; there is no route or CLI to list or revoke them. A leaked admin key needs manual SQL (contradicts ADR 0005). | `control/service.py:803-805`, `cli.py` |
| SEC-04 | medium | done (fix/improvements) | read | **No wall-clock limit on execution.** `execute()` runs synchronously in async handlers (exec, simulate, tests/run, validate, publish); `maxSteps` has no upper bound and cannot limit work (a DAG never exceeds its node count; each `forEach` child gets a fresh budget: 90k child runs with `maxSteps=3`). One slow request freezes the worker, health included. Spec RNF-08 asks for a time limit. | `api/execution.py:121`, `engine/model.py:176`, `engine/compiler.py:468+` |
| SEC-05 | medium | done (fix/improvements) | run | **ReDoS.** Author-supplied regex run with `re.search` on input of any length, no timeout: `^(a+)+$` on 26 `a` + `b` takes 2.4 s, doubling per character. Use a linear-time engine (`re2`) or a timeout, and cap input length. | `engine/expressions.py:154-163` |
| SEC-06 | medium | done (fix/improvements) | run | **Quadratic work on untrusted arrays.** `distinct` uses list membership, `in` on a referenced list scans it: `aurora.studyplan.common` with 20k courses (949 KB, under the 1 MB limit) takes 2.3 s. Use sets/hashable keys; set `maxItems` in example schemas. | `engine/expressions.py:263-267, 399-404` |
| SEC-07 | medium | done (fix/improvements) | run | **Memory amplification from input values.** `"x" * n`, `list * n`, `"%10000000000d" % 1` with `n` from the input allocate gigabytes; `MemoryError` is not caught. | `engine/expressions.py:176-186` |
| SEC-08 | medium | in progress: compose binds to 127.0.0.1; Host allow-list against DNS rebinding open | read | **Default install is open and reachable from the LAN.** compose sets `MINOS_REQUIRE_AUTH=false` and publishes `8000:8000` on 0.0.0.0; every caller is admin. `/v1/*` has no Host allow-list, so DNS rebinding from a web page can drive it (plausible). Bind to `127.0.0.1` by default. | `compose.yaml:29,35`, `api/common.py:64` |
| SEC-09 | medium | done (fix/improvements) | run | **CSRF on import.** `POST /workspaces/{ws}/import` parses the raw body whatever the Content-Type; a cross-site `text/plain` POST needs no preflight (got 200). Require `application/json`. | `api/management.py:572` |
| SEC-10 | medium | done (fix/improvements) | read | **No request size limits.** Exec reads the whole body before its 1 MB check; management (import, draft, tests, infer, simulate) has none; port 8000 bypasses nginx's limit. | `api/execution.py:82-84`, `api/management.py` |
| SEC-11 | medium | done (fix/improvements) | read | **Unauthenticated traffic loads the DB and flushes the key cache.** Each new random key costs a query; at 10,000 entries the whole cache (valid keys too) is cleared. | `api/registry.py:209, 337` |
| SEC-12 | medium | done (fix/improvements) | read | **Auth can silently fail open.** `_bool` treats any unknown value as false, so `MINOS_REQUIRE_AUTH=required`/`enabled`/`y` leaves the API open with an admin principal. Reject unknown values. | `settings.py:10-14` |
| SEC-13 | low | open | read | **`/mcp` itself is unauthenticated** even with auth on (only forwarded calls are checked); anyone can open up to 10,000 sessions and lock clients out. | `mcp/server.py`, `api/app.py` |
| SEC-14 | low | open | read | **Swagger UI from CDN without SRI**, with `persistAuthorization`: a CDN compromise can read API keys from localStorage. | `api/exec_docs.py:23, 307-331` |
| SEC-15 | low | open | read | **Deployment hardening.** API image runs as root; nginx sets no CSP / `frame-ancestors` (clickjacking); images default to seeding examples and serving `examples/rulesets`; workspace slug enumeration via 403 vs 404 (`run`); a DB workspace named `local` can execute the file-served rule sets. | `backend/Dockerfile`, `frontend/nginx.conf`, `api/management.py` |

## Engine

| ID | Sev | Status | Checked | Issue | Where |
| --- | --- | --- | --- | --- | --- |
| ENG-01 | high | done (fix/improvements) | run | **Fail feedback of a group child is emitted when the group passes.** OR group "passport or ID card", input `{"idCard":"X"}`: the run reaches the `valid` end but the outcome is `invalid` with `NO_PASSPORT`. Same for `not`, and for a routing condition (`branch`) with `feedback.fail`. | `engine/compiler.py:389-392`, `engine/runtime.py:214` |
| ENG-02 | high | done (fix/improvements) | run | **Sub-ruleset feedback always copied into the parent.** With `forEach` + `passWhen:"any"`, items `[{ok:false},{ok:true}]` pass the node but the child's error makes the parent `invalid`; same when the sub-ruleset only routes. | `engine/compiler.py:494-498` |
| ENG-03 | high | done (fix/improvements) | run | **Untrusted input crashes execution (HTTP 500) with non-`EvaluationError` exceptions** when validation is off or a field is untyped: `in` with list/dict on the left (`TypeError` unhashable) or non-string left on a string right; `abs("x")`, `floor("x")`; `%` raising `ValueError`/`KeyError`; `inf` into `floor`/`round` (`OverflowError`); `contains` cell with a non-string value; `end.output` evaluated outside the try. | `engine/expressions.py:184, 261, 267, 450, 458, 462`, `engine/decision.py:131`, `engine/runtime.py:143-145` |
| ENG-04 | medium | open | run | **Malformed graphs crash validate/publish instead of a `CompileError`:** pydantic `ValidationError` from `Rule.model_validate`; `{"op":["=="]}` → `TypeError`; ~500 nested expressions → `RecursionError` (orjson accepts 1024 levels). | `engine/compiler.py:376`, `engine/expressions.py:128, 337` |
| ENG-05 | medium | open | run | **Dates ignore time and offset.** `to_date` takes `v[:10]`: `date_before("2027-09-20T23:30:00-05:00", "2027-09-21")` is true; `"2027-09-20garbage"` is accepted; `<` on datetimes compares text; `submittedAt <= today()` is false all day on the reference day. Default reference date is UTC (wrong day in Europe after midnight); the API passes `referenceDate` unnormalised. | `engine/expressions.py:43-54`, `engine/runtime.py:112`, `api/execution.py:126` |
| ENG-06 | medium | done (fix/improvements) | run | **Python equality instead of JSON equality:** `1 == true`, `true in [1,2]`, `distinct([1,true,1.0]) = [1]`, `true + 1 = 2`. | `engine/expressions.py:220, 261, 401`, `engine/decision.py` |
| ENG-07 | medium | open | run | **Rounding is banker's rounding on binary floats:** `round(2.5) = 2`, `round(2.675, 2) = 2.67`, `0.1 + 0.2 == 0.3` false. Fees and credits need half-up and decimals. | `engine/expressions.py:450` |
| ENG-08 | medium | open | run | **Decision tables evaluate every row for every hit policy.** With `first`, a later row that errors (e.g. `>` against a string) turns a matched run into `error`; wasted work on large tables. | `engine/decision.py:153-158` |
| ENG-09 | medium | open | run | **`any`/`all` with `where` and no `select` test truthiness of the elements:** `any([0], where item >= 0)` is false; `all(courses, where cfu >= 6)` is true when nothing matches. Typecheck does not warn. | `engine/expressions.py:393-396` |
| ENG-10 | medium | open | run | **Inferred schemas reject their own samples:** `"2027-09-20T10:15:00"` (no offset), `"… 10:15:00Z"`, `"…T10:15Z"` inferred as `date-time`; `first..last@example.com` as `email`; jsonschema-rs then rejects them. | `schema/infer.py:23, 26` |
| ENG-11 | medium | open | run | **Entity refs under properties named `default`, `enum`, `const`, `examples` are ignored** (`_subschemas` skips data keywords at every level, property names included); `pin_refs` raises a bare `KeyError` for an unknown entity. | `schema/refs.py:60-66, 99` |
| ENG-12 | medium | open | run | **Typecheck rejects valid paths:** `if`/`then`/`else` and `dependentSchemas` not expanded; `"$ref":"#anchor"` resolves to the root; `_expand` stops at 256 entries. | `schema/paths.py:131-148` |
| ENG-13 | medium | open | read | **In `collect_all`, one bad value (e.g. a malformed date) aborts the run as `error`** and hides all other feedback. | `engine/runtime.py:155` |
| ENG-14 | low | open | run | Nested `forEach`: the outer index overwrites the inner one in feedback. | `engine/compiler.py:496-497` |
| ENG-15 | low | open | run | An `end` declared `warning` is never downgraded/upgraded: in `collect_all` violations still give `warning` (check intent). | `engine/runtime.py:212` |
| ENG-16 | low | open | run | `collect` with no matching row returns `null`, not `[]`. | `engine/decision.py:160` |
| ENG-17 | low | open | run | Duplicate switch case names, or a case named `default`, compile silently (dead case). | `engine/compiler.py:184` |
| ENG-18 | low | open | run | Constant values are typechecked as expressions: the constant `{"ref":"not-a-path"}` blocks publishing. | `engine/typecheck.py:222-223` |
| ENG-19 | low | open | run | Templates render lists/dicts as Python repr (`['A', None, True]`) and floats unformatted (`0.30000000000000004`). | `engine/templates.py:20-27` |
| ENG-20 | low | open | run | On `[*]` paths `exists` is always true and `== null` never; conditions use truthiness, so the string `"false"` passes. | `engine/refs.py`, `engine/compiler.py` |
| ENG-21 | low | done (fix/improvements) | run | `regex` uses `search`, not full match: `[0-9]{5}` matches `"abc123456xyz"`. Document it or add `matches`. | `engine/expressions.py:154-163` |

## Control plane

| ID | Sev | Status | Checked | Issue | Where |
| --- | --- | --- | --- | --- | --- |
| CTL-01 | high | done (fix/improvements) | run | **Schema version numbering race:** reads latest, inserts +1, no lock, `IntegrityError` not caught. 3 concurrent saves → 1 ok, 2 HTTP 500. Same via bundle import. Lock the entity row (as `publish` does) or map to 409. | `control/service.py:160-174` |
| CTL-02 | high | done (fix/improvements) | run | **`set_alias` race on a new entry:** `FOR UPDATE` locks nothing when the row does not exist; concurrent first PUTs (or publish `promoteTo` + PUT) → PK violation, HTTP 500. Use `INSERT … ON CONFLICT DO UPDATE`. | `control/service.py:666-677` |
| CTL-03 | high | done (fix/improvements) | run | **Bundle import loses entity references.** Export writes the resolved schema (`#/$defs/entity:Course@1`), which `find_refs` does not see. Same-workspace round trip: `Plan` v1 → v2 with no references, `Course.usedBy` empty, *Update references* gone. Cross-workspace: the copied `$defs["entity:Course@1"]` clashes with the target's own `Course@1` ("two different definitions"). Export the authored form plus the referenced entities, or rename defs on import. | `control/bundle.py:102-104`, `control/service.py:183` |
| CTL-04 | high | done (fix/improvements) | read | **Publish blocks execution traffic.** Test suite and compilation run synchronously on the event loop of the single process that also serves exec, while holding `FOR UPDATE` on the rule set row (which also blocks inserts of its tests and aliases). Run the gate in a thread/worker. | `control/service.py:593`, `api/app.py` |
| CTL-05 | medium | done (fix/improvements) | run | **Seeding can keep the container from starting.** A new example rule set on an existing, user-edited entity is compiled against the edited schema; the 422 aborts `seed-examples`, and the Docker CMD (`migrate && seed && uvicorn`) restart-loops. Skip or isolate failing examples; honour `schemaRef.version`. | `control/examples.py:141-176`, `backend/Dockerfile:20` |
| CTL-06 | medium | open | run | **Oversized strings return 500** (`StringDataRightTruncation`): entity or test name over 200 characters; bundle `referenceDate` with a time into `String(10)` (import bypasses the API pattern). Audit `target` (300) can be exceeded. Validate lengths. | `db/models.py`, `control/service.py:73,121,497`, `control/bundle.py:125-134` |
| CTL-07 | medium | open | run | **Migration 0003 downgrade + upgrade corrupts data:** the re-upgrade backfills `resolved_schema = json_schema`, leaving unresolved `entity:` refs. Re-resolve in the upgrade, or refuse the downgrade when refs exist. | `db/migrations/versions/0003_schema_entity_references.py:20-28` |
| CTL-08 | medium | open | read | **Migration 0002 downgrade deletes every dated alias entry**; an environment with only dated entries disappears (404 in prod). | `db/migrations/versions/0002_alias_effective_from.py:34` |
| CTL-09 | medium | open | run | **An empty test suite passes the publish gate** (spec RF-50 requires tests). | `control/service.py:593-596` |
| CTL-10 | medium | open | read | **The gate is weaker than production:** test inputs are not validated against the schema (production returns 400); tests without `referenceDate` use today and can start failing over time. | `control/service.py:525-535` |
| CTL-11 | medium | open | plausible | **Migrations race at startup:** every replica runs `alembic upgrade` without an advisory lock. | `backend/Dockerfile:20`, `cli.py:39` |
| CTL-12 | medium | open | read | **Settings not validated:** `MINOS_POLL_INTERVAL_S` unparsable crashes with a traceback, ≤ 0 makes a tight DB loop; plain `postgresql://` fails obscurely; no pool or statement-timeout settings. | `settings.py` |
| CTL-13 | low | open | read | Import overwrites the draft without `If-Match` (unsaved Studio work lost); tests absent from the bundle are kept and may block the next publish. | `control/bundle.py:116` |
| CTL-14 | low | open | read | Exporting `?version=X` includes today's tests, not those that gated X (tests are not versioned). | `control/bundle.py:39` |
| CTL-15 | low | open | read | The graph's `schemaRef` is never reconciled with the draft's schema version: versions can claim `@3` and be checked against `@1`. | `control/service.py:335-341, 366-370` |
| CTL-16 | low | open | read | `status` is only ever `published`: the archived/deprecated states (RF-40) do not exist; the archived check is dead code. | `control/service.py:664` |
| CTL-17 | low | open | read | Queries: `list_versions`/`list_schema_versions` load full JSONB to list metadata; N+1 in `entities_referencing`, `schema_references`, `resolver_for`; no indexes on FK columns (`ruleset.entity_id`, `ruleset_alias.version_id`, `ruleset_version.schema_version_id`, `ruleset_draft.schema_version_id`, `api_client.workspace_id`); audit ordered by `id` but indexed on `(workspace_id, ts)`. | `control/service.py:226`, `db/models.py` |
| CTL-18 | low | open | read | `add_schema_version` returns 201 for a no-op; `expected.feedbackCodes` given as a string is compared character by character; a typo in an environment name creates a new environment. | `control/service.py`, `control/testing.py` |

## API and MCP

| ID | Sev | Status | Checked | Issue | Where |
| --- | --- | --- | --- | --- | --- |
| API-01 | high | done (fix/improvements) | run | **One failing reload stops the drift safety net.** In `check_drift` the first `reload_one` that raises (e.g. a version that no longer compiles) aborts the loop: other stale keys and removals are skipped on every poll; reproduced, `z.last` served 0.1.0 forever. `_on_notify` failures keep the old version silently while health says OK. | `api/registry.py:400-401` |
| API-02 | medium | open | run | **A DB workspace named `local` collides with the file-served namespace:** recompiled on every poll, deployments overwritten back and forth, removals never applied. Reserve the slug. | `api/registry.py:396` |
| API-03 | medium | open | read | **MCP `update_ruleset` loses concurrent edits:** it reads the ETag right before the PUT, and `get_ruleset` does not return `lockVersion`, so a Studio save between the AI's read and write is overwritten (docstring promises the opposite). | `mcp/server.py:323-331` |
| API-04 | medium | open | plausible | **Concurrent `reload_one` for the same key can finish out of order**, serving an older snapshot until the next poll; no per-key sequencing. | `api/registry.py:309-313, 369` |
| API-05 | medium | open | read | **MCP `create_entity` is not atomic:** if the schema step fails the entity remains without schema and a retry gets 409. | `mcp/server.py:229-234` |
| API-06 | medium | open | read | **`load_version` errors become plain-text 500** instead of problem+json; unknown versions hit the DB on every request (no negative cache). | `api/execution.py:221` |
| API-07 | low | open | run | Error formats are inconsistent: pydantic errors as `{"detail":[…]}` (not problem+json, input echoed); bad exec bodies 400, bad management bodies 422. | `api/common.py` |
| API-08 | low | open | run | Platform `/openapi.json` incomplete: exec and import bodies undocumented, `diff`'s `from` missing, no `securitySchemes`, only 200/422 responses. | `api/management.py`, `api/exec_docs.py` |
| API-09 | low | done (fix/improvements) | read | Demo mode rebuilds `Settings` and drops `cors_origins` and `studio_url`. | `api/app.py:39-44` |
| API-10 | low | open | read | Swagger summary advertises a version for an environment with only future-dated entries, which returns 404. | `api/exec_docs.py:141` |
| API-11 | low | open | read | nginx overwrites the client's `X-Request-Id` (docs say it is echoed); CORS omits `Mcp-Session-Id` and `MCP-Protocol-Version`. | `frontend/nginx.conf:8`, `api/common.py:85-97` |
| API-12 | low | open | read | `ready`/`health` never degrade (dead LISTEN connection, failing drift, failed loads); `management_app` has neither. | `api/registry.py:294-295`, `api/app.py` |
| API-13 | low | open | read | MCP Host allow-list fixed to localhost (unusable behind a real hostname); nginx does not proxy `/mcp`. | `mcp/server.py`, `frontend/nginx.conf` |

## Studio

| ID | Sev | Status | Checked | Issue | Where |
| --- | --- | --- | --- | --- | --- |
| UI-01 | high | done (fix/improvements) | run | **Decimals cannot be typed in a condition value.** The controlled box re-parses every keystroke and `parseLiteral("1.")` is `1`: typing `3.5` stores **35**. Typing `null` clears the box. Keep the raw text while editing, parse on blur. | `editor/ExpressionEditor.tsx:115`, `editor/expr.ts:116-123` |
| UI-02 | high | done (fix/improvements) | read | **"Save simulation as test" can save the wrong input.** The simulator input lives in local state and is lost when switching tab (selecting a node switches tab), while the result stays: the test is saved with input `{}` and the old expected result. Stale results are never cleared after edits. | `editor/panels.tsx:95, 165-180`, `editor/EditorPage.tsx:354`, `editor/store.ts:112` |
| UI-03 | high | done (fix/improvements) | read | **Unsaved edits silently discarded on refetch.** The draft cache is not updated after save and `refetchOnReconnect` is on: after a network blip the refetched draft differs and `load()` wipes edits, undo history and selection. | `api/hooks.ts:108-114`, `editor/EditorPage.tsx:96-98` |
| UI-04 | high | done (fix/improvements) | run | **The editor freezes on a cyclic graph.** `layered()` loops forever; the backend accepts cycles in drafts (import, API, MCP), so such a draft cannot even be opened to fix it. Guard the layout and reject cycles on save. | `rgd.ts:73-97`, `editor/Canvas.tsx:128`, `editor/graph.ts:92` |
| UI-05 | medium | open | read | Edits made while a save is in flight are marked saved (`dirty=false` unconditionally); Ctrl+S then does nothing and the leave guard does not fire. | `editor/EditorPage.tsx:121-135` |
| UI-06 | medium | open | plausible | Concurrent saves not serialised (Ctrl+S ignores `busy`): two PUTs with the same `If-Match`, the second shows a false "someone else changed the draft". | `editor/EditorPage.tsx:137-145` |
| UI-07 | medium | open | read | A failed validate after a successful save is shown as a save error and aborts Simulate/Tests/Publish. | `editor/EditorPage.tsx:129-133` |
| UI-08 | medium | open | run | **List inputs show stale text and write into another condition** (uncontrolled `defaultValue` under index keys): after removing a condition, blurring the next one stores the removed one's list. Index keys also in group children, args, table rows/columns. | `editor/ConditionBuilder.tsx:117-121, 158-165`, `editor/NodePanel.tsx:270` |
| UI-09 | medium | open | read | Delete on the Start node removes its outgoing edges (node not `deletable:false`). | `editor/Canvas.tsx:234-240` |
| UI-10 | medium | open | read | Multi-node drag keeps only the grabbed node's position; the others snap back. | `editor/Canvas.tsx:245` |
| UI-11 | medium | done (fix/improvements) | plausible | The store is not reset per rule set: if B's draft fails to load, A's graph is shown under B's URL and Ctrl+S could save it into B. | `editor/EditorPage.tsx:173-182` |
| UI-12 | medium | open | plausible | A 401 while editing logs out and loses unsaved changes; after login the cached draft overwrites them. | `api/client.ts:56`, `components/Shell.tsx:33-35` |
| UI-13 | medium | open | run | **Editing an expression cell of a decision table corrupts it**: the JSON is split on commas into a list of strings; output expression cells come back as plain strings. | `editor/cells.ts:77-79, 124-126` |
| UI-14 | medium | in progress: value boxes done (decimal comma for numeric fields, no hex/Infinity); decision-table cells open | run | Values are coerced regardless of the column type: `1,5` (Italian decimal) becomes `[1,5]`; `20100` in a text column becomes a number; `0x10` becomes 16. No hint on quoting. | `editor/cells.ts:28`, `editor/expr.ts:121` |
| UI-15 | medium | open | read | Blur-only fields (variable/output names, branch names, table cells, output columns) are missed by Ctrl+S, which saves the old value and says "Saved"; rejected renames are dropped silently. | `editor/NodePanel.tsx:71-76, 335-341`, `editor/nodeEditors.tsx:76-79, 207-224` |
| UI-16 | medium | open | read | Compose, Edit JSON Schema and Update references build on the *selected* version tab, not the latest: on the v1 tab, Update references saves v1 as v3, dropping v2's fields. If the schema is loading, Compose drops every non-reference field. | `pages/EntityPage.tsx:252, 266-279, 319` |
| UI-17 | medium | open | read | The "update references" warning can stay hidden: `useSchema` has `staleTime: Infinity` but `references[].latest` changes. | `api/hooks.ts:88-95` |
| UI-18 | medium | open | read | Import overwrites drafts and same-name tests without confirmation; `created`, `tests`, `dependencies` (missing sub rule sets) in the result are ignored. | `pages/WorkspacePage.tsx:122-137` |
| UI-19 | medium | open | read | Login and the demo call `/v1/…` directly, ignoring `VITE_MINOS_API`: broken when the API is on another origin. | `pages/LoginPage.tsx:28`, `pages/DemoPage.tsx:108` |
| UI-20 | medium | open | read | `JsonField` keeps the last valid value while the text is invalid: Run, Save schema and Constants use a value different from what is shown. Disable actions while invalid. | `components/forms.tsx:136-145` |
| UI-21 | low | open | read | Async actions without error handling (export from toolbar and version, test delete): unhandled rejections, no feedback. | `editor/EditorPage.tsx:276-279`, `editor/panels.tsx:242-245, 418` |
| UI-22 | low | open | read | `JSON.parse` on a non-JSON error body (HTML 502) throws `SyntaxError`, losing the status and 401 handling. | `api/client.ts:50` |
| UI-23 | low | open | read | Schema inference preview has no cancellation: a slower older response overwrites the newer one. | `pages/EntityPage.tsx:230-242` |
| UI-24 | low | open | read | With two edges between the same nodes, the walked-path highlight picks the first edge, not the port taken. | `editor/Canvas.tsx:159`, `rgd.ts:135` |
| UI-25 | low | open | read | Undo merges any actions within 600 ms (add + connect): one undo reverts both. Undo can leave the editor dirty at the saved state. | `editor/store.ts:80` |
| UI-26 | low | open | read | In the read-only demo, Backspace deletes nodes and edges. | `pages/DemoPage.tsx:157-169` |
| UI-27 | low | open | read | Decision table target field rejects intermediate keystrokes: cannot be cleared and retyped. | `editor/nodeEditors.tsx:128` |
| UI-28 | low | open | read | Raw or hard-coded text: default feedback code `CODICE`, schema source (`manual`, `import`), port names, demo outcome and mode, issue `where` as raw paths, English fetch errors. | `editor/NodePanel.tsx:123`, `pages/EntityPage.tsx:309`, `editor/panels.tsx:682-683`, `pages/DemoPage.tsx:132, 183` |
| UI-29 | low | open | read | Accessibility: status on nodes, edges and minimap shown by colour only; field type hint `aria-hidden`; canvas handles without labels. | `editor/Canvas.tsx`, `editor/FieldPicker.tsx` |

## Functional gaps

What rule authors and operators reasonably need and Minos does not offer yet.

| ID | Sev | Status | Gap |
| --- | --- | --- | --- |
| FN-01 | medium | open | **Lifecycle:** no delete, rename or archive for workspaces, entities, rule sets, versions and tests (no test update either); a rule set's entity cannot change; no rollback endpoint (audit stores `previousVersionId` as a UUID); versions cannot be withdrawn, and `/versions/{semver}` runs unpromoted versions. |
| FN-02 | medium | open | **Publishing:** not idempotent (an unchanged draft publishes 0.0.1, 0.0.2, 0.0.3; the hash includes the version stamp; no idempotency key); no hotfix line (with 2.0.0 scheduled, a fix to 1.4.0 can only be 2.0.1); no promotion policy (any version straight to prod); no way to wait for the rollout after `promoteTo`. |
| FN-03 | medium | open | **Schema evolution:** no schema diff, breaking-change or impact analysis (RF-14); `usedBy` lists only entities, not rule sets, drafts or versions; a draft stays on an old schema version without saying so; `diff_graphs` ignores schema changes. |
| FN-04 | medium | open | **Audit:** actor is `apikey:dev` with auth off and a non-unique key name with auth on; MCP and Studio writes indistinguishable; `list_audit` has only `limit` (no cursor or filters); global events (admin keys) not visible; `draft.save` logged on every save, no retention. |
| FN-05 | medium | open | **Execution API:** no batch execution, rate limiting, quotas, per-request timeout or metrics endpoint (`reloads` is described as observable but nothing exposes it). |
| FN-06 | medium | open | **Management API:** no pagination or filtering on lists (`tests` returns every input); no admin key list/revoke (see SEC-03). |
| FN-07 | medium | open | **MCP:** no tool to replace or delete a test (a wrong test cannot be fixed), to read a published version or a diff; `update_ruleset` needs the whole graph (no patch). |
| FN-08 | medium | open | **Typecheck does not infer expression types:** accepts `count(x) > "a"`, `between` on a string with numeric bounds, `lower(n)` on a number, enum typos (`code == "MBAX"`), non-boolean conditions, `where` on non-aggregates (silently ignored); decision cells not checked against their column; ignores flow (`$.vars` assigned on another branch passes); sub-ruleset `input` not checked against the child schema. |
| FN-09 | medium | open | **Expression language:** no date arithmetic (add days/months), no timezone-aware comparison, no `within_days` (RF-22); `min`/`max` only on numbers (no earliest date); no decimals or half-up rounding; no substring/split/replace; decision cells lack `ends_with`, `regex`, `exists`, `is_null` and cannot match the literal `"-"`; `passWhen` has no count/threshold; `$.outer` reaches one level only. |
| FN-10 | medium | open | **Feedback and explainability:** `path` is static (cannot point at the failing `courses[i]`); templates take references only (no expressions, no number/date formatting); locale must match exactly (`en-US` does not fall back to `en`); trace shows true/false without operand values; sub-ruleset trace dropped; `EvaluationError` does not name the expression or field. |
| FN-11 | medium | open | **Studio validation feedback:** the issue list disappears on the first edit while canvas markers stay stale; clicking an issue does not pan to the node or open the nested part; issues on edges or settings do nothing. |
| FN-12 | medium | open | **Studio editing:** no copy/paste/duplicate of nodes, no node search, node ids cannot be renamed; renaming a variable or output does not update its references; canvas is mouse-only (no "next node" selector, keyboard selection does not open the panel); every add/remove re-fits the whole graph, losing the viewport on large graphs. |
| FN-13 | medium | open | **Studio tests and versions:** cannot view or edit a test's input and expectations, rename it, run one test, or accept the current result; deleting has no confirmation; a saved test asserts the whole `result`. Compare diffs against the *saved* draft only, text-only, no version-to-version, no "restore into draft". Removing an environment entry (prod too) is one click; Promote defaults to prod. |
| FN-14 | medium | open | **Decision tables in the Studio:** output columns cannot be removed, columns cannot be reordered, no multi-cell paste or CSV import, no wider editor than the side panel. |
| FN-15 | low | done (fix/improvements) | Simulation locale defaults to `it` instead of the rule set's locale. |
| FN-16 | low | open | Rule sets and entities cannot be searched; cards and breadcrumbs are not links (no open in new tab). |
| FN-17 | low | open | The entity page does not list the rule sets that use the entity. |
| FN-18 | low | open | Schema version changes are not part of undo. |
| FN-19 | low | open | CLI lacks `revoke-key`, `list-keys`, `downgrade`, `current`; `REPO_EXAMPLES` assumes the repo layout. |
| FN-20 | low | open | Deployment: image tags not pinned by digest; examples served and seeded by default in production images. |

## Code quality

From the static analysis. Baseline at the commit above: ruff (project rules) 0 issues, mypy
`--strict` 0 errors, `tsc` strict with `noUncheckedIndexedAccess` 0 errors, ESLint 0 errors and 14
warnings, backend coverage 98%, `pip-audit` no known vulnerabilities, `npm audit` 0 in runtime
dependencies (7 moderate in dev dependencies), duplicated code 0.46% (jscpd, 7 clones).

| ID | Sev | Status | Issue | Where |
| --- | --- | --- | --- | --- |
| CQ-01 | medium | open | **Expression compiler too complex:** `_compile_op` (168 lines, cyclomatic 46) and `_compile_fn` (166 lines, 34) are single `if/elif` chains; this is where ENG-03/ENG-06 live. Move to a dispatch table, one function per operator, each with its own tests. | `engine/expressions.py:126, 330` |
| CQ-02 | medium | open | **Routers as giant closures:** `management_router` 462 lines (cyclomatic 53), `build_server` (MCP) 303, `execution_router` 189. Split by area (entities, rule sets, tests, environments, keys). | `api/management.py:166`, `mcp/server.py:94`, `api/execution.py:36` |
| CQ-03 | medium | open | **Other functions above cyclomatic 20:** `_Checker.graph` 30, `_Checker.ref` 23, `_Compiler.build` 22, `_compile_node` 22, `CompiledRuleset.execute` 21; `import_bundle`, `DecisionTable.evaluate`, `diff_graphs`, `_compile_test` between 17 and 20. | `engine/typecheck.py`, `engine/compiler.py`, `engine/runtime.py` |
| CQ-04 | medium | open | **Oversized Studio components:** `EditorPage` (~330-line component: state, save, layout, panels), `panels.tsx` (700 lines, 10 components), `NodePanel.tsx` (577 lines; `FeedbackPair` handler copy-pasted 4 times); the uncontrolled-input + blur pattern is reimplemented ~5 times with different validation (root of UI-08, UI-15). Extract one `CommitInput` component. | `frontend/src/editor/` |
| CQ-05 | medium | open | **No component tests:** vitest runs with `environment: 'node'` only; ConditionBuilder, ExpressionEditor, DecisionTableEditor, KeyExprList, JsonField untested; no tests for `parseLiteral` decimals, `formatCell`/`parseCell` round-trip of expression cells, `layered()` on cycles. Playwright covers happy paths only (4 tests). | `frontend/` |
| CQ-06 | low | open | **Logic duplicated between backend and frontend, already diverging:** entity reference grammar (backend: key ≤ 100 chars, version ≥ 1; frontend: any length, `@0` accepted), schema paths (`schema/paths.py` vs `editor/schemaPaths.ts`). Expose the rules from the API or share test fixtures. | `schema/refs.py`, `editor/entityRefs.ts` |
| CQ-07 | low | open | **Duplicated Studio code:** node view copied between `RuleNode.tsx` and `Canvas.tsx` (already diverged: label fallback, exit status, +200 offset, own `Feedback` types); three `portsOf` implementations; repeated sections in `NodePanel.tsx` and `panels.tsx`; `errorText` unused. | `frontend/src/RuleNode.tsx`, `editor/Canvas.tsx`, `rgd.ts:56`, `editor/graph.ts:12` |
| CQ-08 | low | open | **`assert` used for runtime checks** (removed under `python -O`): 8 occurrences. Replace with explicit errors. | `api/management.py:348`, `control/bundle.py:31`, `control/service.py:346, 360, 369, 464`, `engine/refs.py:85`, `schema/refs.py:129` |
| CQ-09 | low | open | Unused arguments (9, e.g. `scope`/`state` in compiler closures, `key` in `registry.py:337`); FastAPI dependency without `Annotated` (`management.py:424`); `input` shadows a builtin in MCP tools. | ruff `ARG`, `FAST002`, `A002` |
| CQ-10 | low | open | ESLint `react-refresh/only-export-components` (14 warnings): files mixing components and helpers (`FieldPicker.tsx`, `ExpressionEditor.tsx`, `forms.tsx`, `main.tsx`). | `frontend/src/` |
| CQ-11 | low | open | Tooling: vulture and radon cannot parse `registry.py` (Python 3.14 `except A, B:`); add dead-code and complexity checks to CI once supported; `npm audit fix` for the dev-only `minimatch` advisory. | CI |
