# Minos Studio · guida rapida

Minos Studio è l'editor web delle regole. Si accede con una API key con scope `manage` del
workspace (o `admin`). Il percorso tipico, senza scrivere JSON:

1. **Entità e schema.** Nel workspace, *Nuova entità*, poi incolla uno o più oggetti di esempio:
   lo schema viene inferito mentre scrivi (tipi, oggetti annidati, liste, date, campi
   obbligatori). Più esempi rendono facoltativi i campi che non compaiono ovunque. *Salva come
   nuova versione*; in alternativa *Modifica JSON Schema* per correggerlo a mano.
2. **Rule set.** *Nuovo rule set*, scegli l'entità. Si apre l'editor con *Inizio → Fine*.
3. **Nodi.** Trascina i nodi dalla palette sul canvas (o fai clic per aggiungerli) e collega le
   uscite (`pass`, `fail`, `next`, i rami dello switch) agli ingressi. Un'uscita ha un solo
   collegamento: trascinarne uno nuovo sostituisce il precedente. I cicli sono impediti.
4. **Configurazione.** Seleziona un nodo per configurarlo nel pannello *Nodo*:
   - *Condizione*: campo, operatore e valore, con gruppi **E/O** annidati e **NON** su ogni
     parte. Gli operatori proposti dipendono dal tipo del campo; le date usano il calendario.
   - *Su una lista*: somma, conteggio, minimo, massimo, media, "tutti", "almeno uno" sugli
     elementi di una lista, con un filtro sugli elementi e un valore calcolato da ciascuno.
   - *Gruppo di regole*: più regole con un messaggio per regola; *Tutte le regole* le valuta
     tutte per raccogliere ogni errore.
   - *Calcolo*: variabili riusabili negli altri nodi (`$.vars.nome`).
   - *Messaggi*: codice, gravità, testo in italiano e inglese con valori inseriti
     (`{{vars.totalCfu}}`), campo interessato e dati allegati.
5. **Impostazioni.** Modalità (*fermati al primo errore* o *raccogli tutti gli errori*), lingua,
   versione dello schema e costanti (soglie, date, listini).
6. **Salva e valida** (`Ctrl+S`). La validazione avviene sul server con lo schema: i problemi
   compaiono in basso, un clic porta al nodo, i nodi con problemi hanno il bordo tratteggiato.
7. **Simula** il draft su un input: il percorso si illumina sul canvas, ogni nodo mostra esito e
   uscita, il pannello riporta messaggi e output. *Salva questa simulazione come test* la
   trasforma in un test di regressione.
8. **Pubblica** dalla scheda *Versioni*: correzione, modifica compatibile o importante. La
   pubblicazione fallisce se il draft non è valido o un test non passa. Si può promuovere subito
   in `dev`, `test` o `prod`, e in seguito spostare ogni ambiente su qualunque versione (anche
   indietro, per un rollback immediato).

Se due persone modificano lo stesso draft, il secondo salvataggio viene rifiutato e lo Studio
propone di ricaricare. Uscire con modifiche non salvate chiede conferma.

Senza database, `/demo` mostra gli esempi Aurora in sola lettura con il simulatore.
