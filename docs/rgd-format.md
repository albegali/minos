# Rule Graph Document (RGD) · format 1.0

A rule set is a JSON document describing a directed acyclic graph of nodes. The authoritative model
is `backend/src/minos/engine/model.py`; full example in
[`examples/rulesets/aurora.studyplan.emba.json`](../examples/rulesets/aurora.studyplan.emba.json).

```json
{
  "rgdVersion": "1.0",
  "ruleset": "aurora.studyplan.emba",
  "version": "0.1.0",
  "schemaRef": { "entity": "StudyPlan", "version": 1 },
  "settings": { "mode": "collect_all", "locale": "it", "maxSteps": 5000 },
  "constants": { "minCfu": 60 },
  "nodes": [],
  "edges": [],
  "ui": { "positions": {} }
}
```

| Field | Meaning |
| --- | --- |
| `ruleset` | Rule set key, used in the URL `POST /v1/exec/{ruleset}` (lowercase, `.`, `-`, `_`) |
| `settings.mode` | `fail_fast` (default) or `collect_all`: changes the default behaviour on failure |
| `settings.locale` | Default message language |
| `settings.maxSteps` | Step limit per execution (error 422 when exceeded) |
| `constants` | Values copied into `$.vars` at the start of every execution |
| `ui` | Editor only (positions, notes): excluded from the version hash |

## Context

Every expression reads from a JSON scope:

| Root | Contents |
| --- | --- |
| `$.input` | The received object, read-only |
| `$.vars` | Constants and variables written by `set` nodes |
| `$.nodes.<id>` | `{ "outcome": "pass" \| "fail", "output": ... }` of the nodes already executed |
| `$.meta` | `ruleset`, `version`, `referenceDate`, `requestId`, `locale` |
| `$.item` | The current item inside `where` / `select` |
| `$.outer` | In a nested aggregation, the item of the outer aggregation |

Reference syntax: `.key`, `["key with spaces"]`, `[n]` (negative too), `[*]` (expands an array:
the result is a list).

## Nodes

| Type | Fields | Output ports |
| --- | --- | --- |
| `start` | | `next` |
| `condition` | `condition`, `onFail?`, `feedback?` | `pass` (required), `fail` |
| `group` | `operator` (`and`/`or`/`not`), `evaluate` (`short_circuit`/`all`), `children`, `onFail?`, `feedback?` | `pass` (required), `fail` |
| `set` | `assign: { name: expression }` writes to `$.vars` | `next` |
| `switch` | `cases: [{ name, when }]`, the first true one wins | every `name` + `default` (all required) |
| `feedback` | `feedback`, `when?` | `next` |
| `decision_table` | `hitPolicy`, `inputs`, `outputs`, `rules`, `target`, `onFail?`, `feedback?` | `pass` (a row matches, required), `fail` |
| `subruleset` | `ruleset`, `version` (pinned), `input?`, `forEach?`, `passWhen?`, `target?`, `onFail?`, `feedback?` | `pass` (required), `fail` |
| `end` | `outcome` (`valid`/`invalid`/`warning`), `output?: { key: expression }` | none |

Edges are `{ "from": id, "to": id, "on": port }` (`on` defaults to `next`). The compiler rejects:
duplicate ids, a missing or repeated start, no end, nonexistent ports or ports connected twice,
unconnected required ports, edges into the start, cycles. Unreachable nodes produce a warning.

The children of a `group` are expressions or rules with their own feedback:
`{ "rule": <expression>, "feedback": { "fail": {...} } }`. With `evaluate: "all"` every child is
evaluated (useful to collect every error); `not` means NOT(AND(children)). A child's `fail`
feedback explains why the group failed, so it is emitted only when the group fails: when an `or`
alternative (or a `not`) makes the group pass, the children that failed report nothing.

### Decision table

```json
{
  "id": "fees", "type": "decision_table", "hitPolicy": "first", "target": "fees",
  "inputs": [
    { "name": "program", "expr": { "ref": "$.input.program.code" } },
    { "name": "cfu", "expr": { "ref": "$.vars.totalCfu" } }
  ],
  "outputs": [{ "name": "baseFee" }, { "name": "discount" }],
  "rules": [
    { "when": ["EMBA", { "op": ">=", "value": 60 }], "then": { "baseFee": 38500, "discount": 0 } },
    { "when": [["MSC", "MBA"], null], "then": { "baseFee": 30000, "discount": 10 } },
    { "when": [null, null], "then": { "baseFee": 25000, "discount": 0 } }
  ]
}
```

One cell per input column: `null` (any), a value (equality), a list (one of),
`{"op": ..., "value": ...}` with `==`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `not_in`, `between`,
`date_before`, `date_after`, `date_between`, `contains`, `starts_with` (the value can be an
expression), or an expression (equality with its value). Outputs are values or expressions.

| Hit policy | Result in `$.vars.<target>` |
| --- | --- |
| `first` | the first matching row |
| `unique` | the only matching row; several rows → execution error |
| `priority` | the row with the highest `priority` (on a tie, the first) |
| `any` | the matching rows must agree; otherwise an error |
| `collect` | the list of matching rows |

If no row matches, the node fails (`fail` port, with the same `onFail` rules as conditions). In
the Studio cells are written in short form: empty or `-`, `EMBA`, `A, B`, `>= 60`, `30..59`,
`2027-01-01..2027-12-31`, `!= X`, `$.vars.name`.

### Sub rule set

Runs another rule set of the same workspace at a **pinned version** (`version` is required: a
published version is immutable, so the result stays reproducible). The version must be published
before validating or publishing the rule set that uses it.

- `input` (default `$.input`): the object passed to the sub rule set.
- `forEach`: a list; the rule set runs once per item (`$.item`, which is also the default
  `input`). `passWhen` = `all` (default) or `any`.
- Outcome: the node passes if the sub rule set is `valid` or `warning` (with `forEach`, according
  to `passWhen`); an `error` stops the execution with outcome `error`.
- `target`: `{ "outcome", "result" }`, or the list of these with `forEach`, in `$.vars`.
- The sub rule set's messages flow into the result with `nodeId` = `<node>/<nested node>` and,
  with `forEach`, the item's `index`: all of them when the node fails, only those of the passing
  runs when it passes (with `passWhen: any` the failing items do not count).

A "dispatcher" (choosing the rule set based on a field) is an ordinary rule set with a `switch`
followed by `subruleset` nodes.

## Failure, exit and outcome

`onFail` policy of a failing `condition`, `group`, `decision_table` or `subruleset` node:

| Policy | Effect | Counts as a violation |
| --- | --- | --- |
| `stop` | Execution ends immediately with outcome `invalid` (`exit.reason = "stop"`) | Yes |
| `continue` | Continues on the `fail` port if connected, otherwise on `pass` | Yes |
| `branch` | Follows the `fail` port (required): flow control only | No |

Default when `onFail` is missing: `branch` if the `fail` port is connected, otherwise `stop` in
`fail_fast` and `continue` in `collect_all`.

Final outcome: that of the `end` reached; an `end` declared `valid` becomes `invalid` if there are
violations or feedback with severity `error`, and `warning` if there are only warnings. With
`branch`, a failing node still emits its `fail` feedback: give it severity `info` (or none) when
the failure is only a routing decision. An evaluation error (e.g. comparing incompatible types,
or a value of an unexpected type when schema validation is off) ends with outcome `error`; its
message is cut to 300 characters.

## Type-check on publication

Validation and publication compile the graph against the entity schema and reject (all at once):
`$.input` / `$.item` / `$.outer` references that do not exist in the schema, variables that are
neither constants nor assigned by a `set` node, nonexistent nodes or `meta` keys, aggregations over
fields that are not arrays (or not numeric for `sum`/`min`/`max`/`avg`), comparisons with literals
of an incompatible type. The same applies to the `{{...}}` placeholders in messages. Undeclared
properties of an object with `properties` are treated as nonexistent, unless
`additionalProperties` allows them.

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

On `condition` and `group` (and on group children) you define `feedback.pass` and
`feedback.fail`. `{{...}}` placeholders are references without `$.`. Language: the requested one,
then the rule set's default, then the first available.

## Expressions

JSON literals; lists of expressions; `{"literal": <any JSON>}` for literal objects;
`{"ref": "$...."}`; operators `{"op": ..., "left": ..., "right": ...}` (or `"args": [...]` or
`"arg"`); functions `{"fn": ..., "args": [...]}`.

| Operators | Notes |
| --- | --- |
| `==` `!=` | `null` and a missing field are equivalent |
| `<` `<=` `>` `>=` | `false` if one side is missing; error if the types are not comparable |
| `between` | `right: [min, max]`, bounds included |
| `date_before` `date_after` `date_between` | Compares the date part (ISO `YYYY-MM-DD...`) |
| `in` `not_in` | `right` a literal list or a reference to a list |
| `contains` `starts_with` `ends_with` `regex` | `regex` requires a literal pattern |
| `exists` `is_null` `is_not_null` | `exists` tells a missing field from `null` |
| `and` `or` `not` `if` | `if`: `args: [condition, then, else]` |
| `+` `-` `*` `/` `%` | `null` if an operand is missing |

| Functions | Notes |
| --- | --- |
| `sum` `count` `min` `max` `avg` `any` `all` `distinct` `filter` `map` | One array argument; optional `where` (filter) and `select` (projection) with `$.item` |
| `len` `lower` `upper` `trim` `coalesce` `round` `abs` `floor` | |
| `date` `today` `days_between` `age` | `today` and `age` use `meta.referenceDate` (settable per request) |

## Execution result

```json
{
  "requestId": "…",
  "ruleset": "aurora.studyplan.emba",
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

`trace` is `null` with `options.trace = "none"`, the list of steps with `summary`, and includes
output and microseconds per node with `full`.
