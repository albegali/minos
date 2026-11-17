# 0004 · Editor UI kit

- Status: Accepted (F2)
- Date: 2026-11-16

## Context

The editor must be embeddable in Dynamics 365 (web resource or iframe) and in other portals.

## Decision

**Fluent UI 2** (`@fluentui/react-components` v9): visual consistency with Dynamics and the Power
Platform, careful accessibility, light and dark themes (following `prefers-color-scheme`).

Rejected: shadcn/ui + Tailwind. More flexible, but it does not look like Microsoft and the
components have to be maintained in the repo.

## Consequences

- The canvas stays on React Flow with its own styles; the rest of the interface uses Fluent
  components and tokens (`--colorNeutral…`).
- Fluent copies the `FluentProvider` `className` onto portal containers (dialogs, menus): layout
  classes belong on an inner element, not on the provider.
- The bundle exceeds 500 kB minified: to be split (per-route code splitting) in F3.
