# 0004 · UI kit dell'editor

- Stato: Accettata (F2)
- Data: 2026-11-16

## Contesto

L'editor deve poter essere ospitato in Dynamics 365 (web resource o iframe) e in altri portali.

## Decisione

**Fluent UI 2** (`@fluentui/react-components` v9): coerenza visiva con Dynamics e Power
Platform, accessibilità curata, temi chiaro e scuro (seguono `prefers-color-scheme`).

Scartata shadcn/ui + Tailwind: più flessibile, ma l'aspetto non è Microsoft e i componenti
vanno mantenuti nel repo.

## Conseguenze

- Il canvas resta React Flow con stili propri; il resto dell'interfaccia usa i componenti e i
  token di Fluent (`--colorNeutral…`).
- Fluent copia la `className` del `FluentProvider` sui contenitori dei portali (dialog, menu):
  le classi di layout vanno su un elemento interno, non sul provider.
- Il bundle supera i 500 kB minificati: da suddividere (code splitting per rotta) in F3.
