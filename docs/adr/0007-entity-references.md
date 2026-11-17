# 0007 · Entities that reference other entities

- Status: Accepted
- Date: 2026-11-17

## Context

A rule set validates one entity. Real inputs are often made of several kinds of object: a
student, their study plan, the program and its courses. Until now a rule set could read them in
two ways. One was a single entity whose schema copies every part, repeated in each entity that
needs it. The other was splitting the rules across rule sets chained with `subruleset` nodes,
one per entity. With `subruleset` the rules cannot compare parts with each other (a course in
the plan against the program's offering), and each part needs its own published rule set.

## Decision

- **An entity can be the type of a field.** A schema writes `{"$ref": "entity:Course"}`
  (`{"type": "array", "items": {"$ref": "entity:Course"}}` for a list), anywhere in the schema,
  so references nest (a `Program` with its `Course`s, an `Enrollment` with its `Program`).
- **References are pinned when the schema is saved.** `entity:Course` becomes
  `entity:Course@<latest>`, or the version given explicitly (`entity:Course@2`) is kept. A
  published rule set therefore never changes shape when a referenced entity gets a new version.
  Saving the schema again unpinned moves the references forward, as a new version. The Studio
  offers this as *Update references* when a referenced entity has a newer version.
- **Each version is stored twice.** `json_schema` holds the schema as written, with references
  pinned; the hash covers this form, and it is what people edit. `resolved_schema` holds a
  standalone JSON Schema: every referenced version is placed under
  `$defs["entity:<key>@<version>"]` and the references become local
  (`#/$defs/entity:Course@2`). Nested references are lifted to the root, so each entity appears
  once. Type-check, input validation, the Swagger and bundles use the resolved form; they already
  handle local `$ref`, so the engine does not change.
- **Resolution is one level deep and acyclic by construction.** A reference can only point at a
  version that already exists. Versions are immutable, and their resolved form is already
  complete.
- **Only annotations next to a reference.** `title` and `description` are allowed beside
  `$ref`; constraints belong in the referenced entity, so they cannot silently change it in one
  place only.

## Consequences

- One rule set reads every part of a composite input directly (`$.input.student.birthDate`,
  `$.input.program.courses[*].cfu`) and can compare the parts with each other. `subruleset`
  remains the tool for reusing whole, already published rule sets.
- Execution validates the whole composite input against every embedded entity in one pass, with
  JSON pointers to the wrong field (`/program/courses/0/cfu`).
- Bundles carry the resolved schema, so they import into workspaces without the referenced
  entities. The trade-off is that the imported entity no longer links to them.
- A change to a shared entity reaches its users only when they update their references:
  explicit, but one step per referencing entity (*Used by* on the entity page shows which
  ones).
