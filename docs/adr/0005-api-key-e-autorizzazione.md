# 0005 · API key e autorizzazione

- Stato: Accettata
- Data: 2026-11-16

## Contesto

Sistemi terzi (Dynamics, portali, ETL) chiamano l'Execution API migliaia di volte al minuto;
Studio e CI usano la Management API. L'autenticazione non deve aggiungere latenza percepibile.

## Decisione

- **API key** casuali a 256 bit con prefisso `mns_`, salvate come **SHA-256**. Un hash lento
  (Argon2, bcrypt) serve a proteggere segreti a bassa entropia come le password; per un token
  casuale non aggiunge sicurezza e costerebbe millisecondi a ogni chiamata. Questo sostituisce
  l'indicazione "Argon2" della prima versione delle specifiche (RNF-09).
- **Scope**: `admin` (globale), `manage` ed `exec` (legati a un workspace). La chiave in chiaro è
  mostrata una sola volta; nel database restano hash e prefisso leggibile.
- L'Execution API tiene una **cache in memoria** chiave → principal (60 s; 5 s per le chiavi
  non valide). La revoca invia una NOTIFY che svuota la voce nei worker, quindi ha effetto entro
  pochi millisecondi anche prima della scadenza.
- La Management API verifica la chiave sul database a ogni richiesta (non è sul percorso caldo).
- Utenti e ruoli dell'editor (OIDC con Entra ID o Google, RBAC Owner/Editor/Reviewer/Viewer)
  arrivano in F2; le API key restano per i sistemi.

## Conseguenze

- Una chiave compromessa si revoca da `DELETE /v1/workspaces/{ws}/api-keys/{id}`.
- `MINOS_REQUIRE_AUTH=false` disattiva i controlli: solo per sviluppo locale.
