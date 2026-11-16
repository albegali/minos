# 0004 · UI kit dell'editor

- Stato: Proposta
- Data: 2026-11-16

## Contesto

L'editor deve poter essere ospitato in Dynamics 365 (web resource o iframe) e in altri portali.

## Opzioni

1. **Fluent UI 2** (`@fluentui/react-components`): coerenza visiva con Dynamics e Power Platform,
   accessibilità curata, temi chiaro/scuro.
2. **shadcn/ui + Tailwind**: più flessibile e leggero, ma aspetto non Microsoft.

## Stato attuale

L'anteprima F0 usa CSS semplice con variabili per tema chiaro e scuro, così da non legarsi a
nessuno dei due. La scelta va fatta prima di F2 (Editor MVP).
