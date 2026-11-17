import { describe, expect, it } from 'vitest'

import { exitReasonText, feedbackText, PLACEHOLDER_PATTERNS, translateApiText } from './api'
import en from './locales/en.json'
import itCatalog from './locales/it.json'

// Messages produced by the backend (compile_ruleset, typecheck, control.testing, API).
const cases: [string, string][] = [
  ['exactly one start node required, found 2', 'serve esattamente un nodo di inizio, trovati 2'],
  ["unknown target node 'ghost'", "nodo di destinazione sconosciuto 'ghost'"],
  ['edges cannot point to the start node', 'i collegamenti non possono entrare nel nodo di inizio'],
  ["operator '>' expects 2 operand(s), got 3", "l'operatore '>' richiede 2 operandi, ricevuti 3"],
  [
    'sum() needs an array, $.input.customer is a field of type object',
    'sum() richiede una lista, $.input.customer è un campo di tipo object',
  ],
  ["unknown operator 'frobnicate'", "operatore sconosciuto 'frobnicate'"],
  [
    "bad placeholder '{{zzz.a}}': reference root must be one of ['input', 'vars']: '$.zzz.a'",
    "segnaposto non valido '{{zzz.a}}': la radice del riferimento deve essere una tra ['input', 'vars']: '$.zzz.a'",
  ],
  ["outcome: expected 'valid', got 'invalid'", "esito: atteso 'valid', ottenuto 'invalid'"],
  ["feedbackCodes: missing ['A'], unexpected ['B']", "codici dei messaggi: mancano ['A'], inattesi ['B']"],
  ['result.total: expected 3, got 4', 'result.total: atteso 3, ottenuto 4'],
  ['result.x: missing', 'result.x: mancante'],
  ["workspace 'esempi' not found", "workspace 'esempi' non trovato"],
  ['draft changed since version 3 (now 4)', 'il draft è cambiato dalla versione 3 (ora 4)'],
  [
    "invalid ruleset key 'A B': lowercase letters, digits, '.', '-', '_'",
    "chiave del rule set 'A B' non valido: ammessi solo lettere minuscole, cifre, '.', '-', '_'",
  ],
  [
    "'==' compares a field of type number with a string literal: it is always false",
    "'==' confronta un campo di tipo number con un valore string: è sempre falso",
  ],
  [
    "$.input.nope does not exist in the entity schema (+2 more)",
    "$.input.nope non esiste nello schema dell'entità (+2 altri)",
  ],
  [
    "sub-ruleset common@1.0.0 (element 2) failed: not a date: 'x'; unknown function 'f'",
    "rule set annidato common@1.0.0 (elemento 2) non riuscito: non è una data: 'x'; funzione sconosciuta 'f'",
  ],
]

describe('backend messages', () => {
  it.each(cases)('translates %s', (message, italian) => {
    expect(translateApiText(message, 'it')).toBe(italian)
  })

  it('leaves English and unknown messages as they are', () => {
    expect(translateApiText("unknown operator 'x'", 'en')).toBe("unknown operator 'x'")
    expect(translateApiText('something new', 'it')).toBe('something new')
    expect(translateApiText('Field required (1 error(s))', 'it')).toBe('Field required (errori: 1)')
  })

  it('recognises every template, placeholders included', () => {
    const constrained = Object.keys(PLACEHOLDER_PATTERNS).map((name) => `{${name}}`)
    for (const [key, template] of Object.entries(en.api)) {
      if (constrained.some((p) => template.includes(p))) continue // covered by the cases above
      expect(translateApiText(template, 'it'), template).toBe(itCatalog.api[key as keyof typeof en.api])
    }
  })

  it('translates engine errors in feedback only, and exit reasons', () => {
    expect(feedbackText({ code: 'MINOS_EVALUATION_ERROR', message: "not a date: 'x'" }, 'it')).toBe("non è una data: 'x'")
    expect(feedbackText({ code: 'MY_CODE', message: "not a date: 'x'" }, 'it')).toBe("not a date: 'x'")
    expect(exitReasonText('stop', 'it')).toBe('interrotto')
  })
})
