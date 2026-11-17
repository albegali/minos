# Writing Minos rules from a description

Minos is a JSON rule engine. Rules live in a **workspace**; each rule set validates one
**entity** (the JSON object it receives, described by a JSON Schema) and is a graph of nodes
(the Rule Graph Document, RGD, described below). People review, simulate and publish rule sets
in Minos Studio; these tools only create and change **drafts**: never tell the user that a rule
set is published or live, give them the Studio link to review it.

## Workflow

1. `list_workspaces`, then `list_entities` / `list_rulesets`: reuse what exists. Create a
   workspace only if the user asks for a new one or none fits. Workspace `esempi`, when present,
   holds complete published examples (study plan, e-commerce order, loan): `get_ruleset` on them
   shows real graphs with decision tables, nested rule sets and aggregates.
2. **Entity.** If the object to validate is not there yet, `create_entity` with one or more
   realistic example objects (`samples`): the schema is inferred from them (types, nested
   objects, lists, dates, required fields; a field missing from some samples becomes optional).
   Ask the user for a sample or build a plausible one from their description and say so. Pass
   `json_schema` instead only when the user gives a schema. `get_entity` shows the schema: every
   `$.input...` reference must exist in it.
   **Several objects** (e.g. a student, their study plan, the program and its courses): create
   one entity per kind of object from its own samples, then an entity for what the rule set
   receives, with `json_schema` using `{"$ref": "entity:<key>"}` as the type of a field
   (`{"type": "array", "items": {"$ref": "entity:Course"}}` for a list). References work inside
   any entity too (a `Program` with a list of `Course`). A rule set on the composite entity reads
   every part directly (`$.input.student.age`, `$.input.program.courses[*].cfu`): no
   `subruleset` is needed. A reference is pinned to the entity's latest version when saved; to
   move it after the referenced entity changes, save the schema again with `update_entity_schema`.
   A reference carries only `title`/`description`: constraints belong in the referenced entity.
3. **Rule set.** Write the RGD graph and call `create_ruleset`. Put thresholds, dates and lists
   that the business may change in `constants` (read as `$.vars.<name>`), not inline. Give every
   check a `feedback` with a stable `code`, `severity` and a clear message (`it` and `en`).
   Prefer `settings.mode: "collect_all"` when the user wants every problem reported at once.
   Omit `ui`: the Studio lays the graph out.
4. **Fix until valid.** `create_ruleset` and `update_ruleset` save the draft and return the
   validation result. Fix every issue (unknown fields, type mismatches, unconnected ports) with
   `update_ruleset` until `valid` is true.
5. **Prove it.** `simulate_ruleset` with a passing and a failing input; check `outcome`,
   `feedback` and `result`. Save the meaningful cases with `add_test` (they gate publication)
   and `run_tests`.
6. **Hand over.** Summarise what the rules check and end with the `studioUrl` so the user can
   review, adjust and publish.

## Small complete example

Order with lines; reject empty orders, require a total of at least 10, warn above 5,000:

```json
{
  "rgdVersion": "1.0",
  "ruleset": "shop.order.basic",
  "settings": { "mode": "collect_all", "locale": "it" },
  "constants": { "minTotal": 10, "reviewAbove": 5000 },
  "nodes": [
    { "id": "start", "type": "start" },
    { "id": "total", "type": "set", "label": "Totale",
      "assign": { "total": { "fn": "sum", "args": [{ "ref": "$.input.lines" }],
                            "select": { "op": "*", "left": { "ref": "$.item.quantity" },
                                        "right": { "ref": "$.item.unitPrice" } } } } },
    { "id": "checks", "type": "group", "label": "Controlli", "operator": "and",
      "evaluate": "all",
      "children": [
        { "rule": { "op": ">", "left": { "fn": "count", "args": [{ "ref": "$.input.lines" }] },
                    "right": 0 },
          "feedback": { "fail": { "code": "ORD_EMPTY", "severity": "error", "path": "lines",
                                  "message": { "it": "L'ordine è vuoto", "en": "The order is empty" } } } },
        { "rule": { "op": ">=", "left": { "ref": "$.vars.total" }, "right": { "ref": "$.vars.minTotal" } },
          "feedback": { "fail": { "code": "ORD_MIN", "severity": "error",
                                  "message": { "it": "Totale minimo {{vars.minTotal}}",
                                               "en": "Minimum total {{vars.minTotal}}" } } } }
      ] },
    { "id": "big", "type": "feedback",
      "when": { "op": ">", "left": { "ref": "$.vars.total" }, "right": { "ref": "$.vars.reviewAbove" } },
      "feedback": { "code": "ORD_REVIEW", "severity": "warning",
                    "message": { "it": "Ordine da verificare", "en": "Order to review" } } },
    { "id": "ok", "type": "end", "outcome": "valid", "output": { "total": { "ref": "$.vars.total" } } },
    { "id": "ko", "type": "end", "outcome": "invalid" }
  ],
  "edges": [
    { "from": "start", "to": "total" },
    { "from": "total", "to": "checks" },
    { "from": "checks", "to": "big", "on": "pass" },
    { "from": "checks", "to": "ko", "on": "fail" },
    { "from": "big", "to": "ok" }
  ]
}
```

The format reference follows.
