import { afterEach, describe, expect, it } from 'vitest'

import { describe as describeExpr } from '../editor/expr'
import { canConnect } from '../editor/graph'
import en from './locales/en.json'
import itCatalog from './locales/it.json'
import { localize, translate, useLang } from '.'

function keys(node: unknown, prefix = ''): string[] {
  return Object.entries(node as Record<string, unknown>).flatMap(([k, v]) =>
    typeof v === 'string' ? [`${prefix}${k}`] : keys(v, `${prefix}${k}.`),
  )
}

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort()

function leaf(catalog: unknown, key: string): string {
  return key.split('.').reduce<unknown>((n, part) => (n as Record<string, unknown>)[part], catalog) as string
}

describe('catalogues', () => {
  it('have the same keys in every language', () => {
    expect(keys(en).sort()).toEqual(keys(itCatalog).sort())
  })

  it('use the same placeholders in every language', () => {
    for (const key of keys(itCatalog)) {
      expect(placeholders(leaf(en, key)), key).toEqual(placeholders(leaf(itCatalog, key)))
    }
  })
})

describe('translate', () => {
  afterEach(() => useLang.setState({ lang: 'it' }))

  it('fills placeholders and picks plural forms', () => {
    expect(translate('it', 'editor.problems', { count: 1 })).toBe('1 problema')
    expect(translate('it', 'editor.problems', { count: 3 })).toBe('3 problemi')
    expect(translate('en', 'editor.problems', { count: 1 })).toBe('1 problem')
    expect(translate('en', 'editor.saved', { rev: 4 })).toBe('Saved (rev. 4)')
  })

  it('leaves template syntax of rule messages alone', () => {
    expect(translate('en', 'node.templateHint', {})).toContain('{{vars.name}}')
  })

  it('localizes API objects with a fallback to Italian', () => {
    expect(localize({ it: 'Fine', en: 'End' }, 'en')).toBe('End')
    expect(localize({ it: 'Fine' }, 'en')).toBe('Fine')
    expect(localize(undefined, 'en')).toBe('')
  })

  it('switches the pure editor helpers with the language', () => {
    useLang.setState({ lang: 'en' })
    expect(describeExpr({ op: 'between', left: { ref: '$.input.n' }, right: [1, 5] })).toBe('n between 1 and 5')
    const g = { rgdVersion: '1.0' as const, ruleset: 'x', nodes: [{ id: 'a', type: 'start' as const }], edges: [] }
    expect(canConnect(g, 'a', 'next', 'a').reason).toBe('a node cannot connect to itself')
  })
})
