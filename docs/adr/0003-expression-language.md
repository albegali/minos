# 0003 · Expressions as a closed-grammar JSON AST

- Status: Accepted for the JSON AST; Proposed for the textual syntax
- Date: 2026-11-16

## Context

The no-code editor generates conditions; expert users also want to write them. Expressions must be
safe (no arbitrary code, no infinite loops), checkable against the schema, and fast.

## Decision

- The canonical form is a **JSON AST** (`{"op": ..., "left": ..., "right": ...}`,
  `{"fn": ..., "args": [...], "where": ..., "select": ...}`, `{"ref": "$.input..."}`), inspired by
  JsonLogic but with typed operators and aggregation functions. Full reference in
  [`docs/rgd-format.md`](../rgd-format.md).
- **Closed** grammar: only the operators and functions registered in the compiler; no `eval`.
  Array filters use `where` with `$.item` instead of JSONPath `[?()]`; in nested aggregations the
  outer item is `$.outer` (added in F1 for rules such as "credits per term").
- Missing references evaluate to `MISSING`: comparisons return `false`, arithmetic returns `null`,
  type errors become `EvaluationError` (outcome `error`).

## To be decided (by F1)

- Textual syntax for expert users, parsed in the compiler with Lark: a language of our own or a
  subset compatible with CEL or FEEL.
- ~~Type-checking expressions against the entity schema~~: done in F1
  (`minos.engine.typecheck`), run on every validation and publication.
