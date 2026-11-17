// Studio translations. The labels live in locales/<lang>.json; Italian is the reference
// catalogue (and the fallback for a missing key), every other language must have the same keys.
//
// Placeholders are written `{name}` and filled from `params`; a key with a `_one` variant
// (e.g. `editor.problems_one`) is picked by the plural rules when `params.count` is given.
// The chosen language is kept in localStorage; storage can be unavailable, so every access
// is guarded.

import { createElement, Fragment, type ReactNode, useMemo } from 'react'
import { create } from 'zustand'

import en from './locales/en.json'
import it from './locales/it.json'

export type Messages = typeof it
export const LANGUAGES = ['it', 'en'] as const
export type Lang = (typeof LANGUAGES)[number]
export const LANGUAGE_NAMES: Record<Lang, string> = { it: 'Italiano', en: 'English' }

// Assigning to `Messages` makes the build fail when a translation lacks a key.
const CATALOGS: Record<Lang, Messages> = { it, en }

type Leaves<T, P extends string = ''> = {
  [K in keyof T & string]: T[K] extends string ? `${P}${K}` : Leaves<T[K], `${P}${K}.`>
}[keyof T & string]

/** Every translation key, as a dotted path: `editor.save`. */
export type Key = Leaves<Messages>
export type Params = Record<string, string | number>

const STORAGE_KEY = 'minos.lang'

const isLang = (v: unknown): v is Lang => LANGUAGES.includes(v as Lang)

function initialLang(): Lang {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (isLang(stored)) return stored
  } catch {
    // no storage: fall through to the browser language
  }
  const nav = typeof navigator === 'undefined' ? '' : (navigator.language ?? '')
  return nav.toLowerCase().startsWith('it') ? 'it' : 'en'
}

function applyToDocument(lang: Lang) {
  if (typeof document !== 'undefined') document.documentElement.lang = lang
}

interface LangState {
  lang: Lang
  setLang: (lang: Lang) => void
}

export const useLang = create<LangState>((set) => ({
  lang: initialLang(),
  setLang: (lang) => {
    try {
      localStorage.setItem(STORAGE_KEY, lang)
    } catch {
      // the choice lasts for this page only
    }
    applyToDocument(lang)
    set({ lang })
  },
}))
applyToDocument(useLang.getState().lang)

function lookup(lang: Lang, key: string): string | undefined {
  let node: unknown = CATALOGS[lang]
  for (const part of key.split('.')) node = (node as Record<string, unknown> | undefined)?.[part]
  return typeof node === 'string' ? node : undefined
}

function template(lang: Lang, key: Key, params?: Params): string {
  if (typeof params?.count === 'number') {
    const plural = lookup(lang, `${key}_${new Intl.PluralRules(lang).select(params.count)}`)
    if (plural) return plural
  }
  return lookup(lang, key) ?? lookup('it', key) ?? key
}

const PLACEHOLDER = /\{(\w+)\}/g

export function translate(lang: Lang, key: Key, params?: Params): string {
  const text = template(lang, key, params)
  if (!params) return text
  return text.replace(PLACEHOLDER, (match, name: string) => (name in params ? String(params[name]) : match))
}

/** Like `translate`, but placeholders can be filled with elements (`<code>`, links, …). */
export function translateRich(lang: Lang, key: Key, params: Record<string, ReactNode>): ReactNode {
  const parts = template(lang, key).split(PLACEHOLDER)
  // split() with a capture group alternates text and placeholder names
  return parts.map((part, i) =>
    createElement(Fragment, { key: i }, i % 2 === 1 ? (part in params ? params[part] : `{${part}}`) : part),
  )
}

/** Pick the current language from a `{it: …, en: …}` object of the API. */
export function localize(value: Record<string, string> | undefined, lang: Lang): string {
  if (!value) return ''
  return value[lang] ?? value.it ?? Object.values(value)[0] ?? ''
}

/** BCP 47 locale for dates and numbers. */
export const dateLocale = (lang: Lang) => (lang === 'it' ? 'it-IT' : 'en-GB')

/**
 * Translation outside React (pure helpers such as `describe`). Components calling such
 * helpers also use `useI18n`, so they re-render when the language changes.
 */
export function t(key: Key, params?: Params): string {
  return translate(useLang.getState().lang, key, params)
}

export function useI18n() {
  const lang = useLang((s) => s.lang)
  return useMemo(
    () => ({
      lang,
      t: (key: Key, params?: Params) => translate(lang, key, params),
      rich: (key: Key, params: Record<string, ReactNode>) => translateRich(lang, key, params),
      loc: (value: Record<string, string> | undefined) => localize(value, lang),
      dateLocale: dateLocale(lang),
    }),
    [lang],
  )
}
