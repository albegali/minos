// Translation of the messages the backend writes (validation issues, errors, test
// differences, evaluation errors). The backend speaks English and has no message codes, so
// the messages are recognised by their text: the English catalogue holds, under `api` and
// `apiTerms`, the backend templates word for word (`workspace {name} not found`), and each
// becomes a pattern. A message nobody recognises is shown as it is.
//
// Templates are tried in catalogue order, so generic ones (`{path}: missing`) come last.
// Fragile by design: when a backend message changes, update its template in en.json (and
// the translation in it.json), otherwise that message stays in English.

import { type Key, type Lang, type Params, translate, useLang } from '.'
import en from './locales/en.json'

interface Rule {
  key: Key
  pattern: RegExp
  names: string[]
}

/** Placeholders whose value is itself a backend message (or a piece of one). */
const NESTED = new Set(['message', 'messages', 'what', 'place', 'field', 'always'])
const MAX_DEPTH = 4
/**
 * Narrower patterns for placeholders followed by another one, where `.+?` would split the
 * text in the wrong place (`invalid {what} {value}`: what is `ruleset key`).
 */
export const PLACEHOLDER_PATTERNS: Record<string, string> = { what: '[a-z]+ (?:slug|key)' }

function compile(group: 'api' | 'apiTerms'): Rule[] {
  return Object.entries(en[group]).map(([name, template]) => {
    const names: string[] = []
    const source = template
      .split(/(\{\w+\})/)
      .map((part) => {
        const placeholder = /^\{(\w+)\}$/.exec(part)
        if (placeholder?.[1]) {
          names.push(placeholder[1])
          return `(${PLACEHOLDER_PATTERNS[placeholder[1]] ?? '.+?'})`
        }
        return part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      })
      .join('')
    return { key: `${group}.${name}` as Key, pattern: new RegExp(`^${source}$`, 's'), names }
  })
}

let rules: { messages: Rule[]; terms: Rule[] } | null = null

function match(text: string, list: Rule[], lang: Lang, depth: number): string | null {
  for (const rule of list) {
    const m = rule.pattern.exec(text)
    if (!m) continue
    const params: Params = {}
    rule.names.forEach((name, i) => {
      const value = m[i + 1] ?? ''
      if (!NESTED.has(name) || depth >= MAX_DEPTH) params[name] = value
      else if (name === 'messages') {
        params[name] = value
          .split('; ')
          .map((part) => translateApiText(part, lang, depth + 1))
          .join('; ')
      } else params[name] = translateApiText(value, lang, depth + 1)
    })
    return translate(lang, rule.key, params)
  }
  return null
}

/** The backend message `text` in `lang` (default: the Studio language), when recognised. */
export function translateApiText(text: string, lang: Lang = useLang.getState().lang, depth = 0): string {
  if (lang === 'en' || !text) return text
  rules ??= { messages: compile('api'), terms: compile('apiTerms') }
  // A type-check error lists its first issue followed by " (+N more)".
  const more = /^(.*) \(\+(\d+) more\)$/s.exec(text)
  if (more?.[1] && more[2]) {
    return `${translateApiText(more[1], lang, depth)} ${translate(lang, 'apiTerms.more', { count: Number(more[2]) })}`
  }
  return match(text, rules.messages, lang, depth) ?? match(text, rules.terms, lang, depth) ?? text
}

/** Engine errors raised while running a node become feedback with this code. */
export const EVALUATION_ERROR = 'MINOS_EVALUATION_ERROR'

/** Text of a feedback entry: authors' messages already follow the requested locale. */
export function feedbackText(f: { code: string; message: string }, lang?: Lang): string {
  return f.code === EVALUATION_ERROR ? translateApiText(f.message, lang) : f.message
}

/** Exit reason of an execution (`end`, `stop`, `error`). */
export function exitReasonText(reason: string, lang: Lang = useLang.getState().lang): string {
  return ['end', 'stop', 'error'].includes(reason) ? translate(lang, `exitReason.${reason}` as Key) : reason
}
