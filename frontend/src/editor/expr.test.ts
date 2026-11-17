import { describe, expect, it } from 'vitest'

import { describe as text, isComparison, isGroup, literalText, operands, parseLiteral, toggleNot } from './expr'

describe('expression helpers', () => {
  it('renders expressions compactly', () => {
    expect(text({ op: '>=', left: { ref: '$.input.age' }, right: 18 })).toBe('age ≥ 18')
    expect(
      text({
        op: 'and',
        args: [
          { op: '==', left: { ref: '$.input.track' }, right: 'FIN' },
          { op: 'or', args: [{ op: 'exists', arg: { ref: '$.vars.x' } }, true] },
        ],
      }),
    ).toBe('track = "FIN" E (vars.x presente O true)')
    expect(text({ op: 'not', arg: { op: '==', left: { ref: '' }, right: '' } })).toBe('NON ? = ""')
    expect(
      text({ fn: 'sum', args: [{ ref: '$.input.courses' }], select: { ref: '$.item.cfu' }, where: { op: '==', left: { ref: '$.item.area' }, right: 'FIN' } }),
    ).toBe('sum(courses di item.cfu dove item.area = "FIN")')
    expect(text({ op: 'between', left: { ref: '$.input.n' }, right: [1, 5] })).toBe('n tra 1 e 5')
    expect(text([1, 'a'])).toBe('[1, "a"]')
    expect(text({ literal: { a: 1 } })).toBe('{"a":1}')
    expect(text({ op: 'if', args: [true, 1, 2] })).toBe('se true …')
  })

  it('classifies and reads operands', () => {
    expect(isGroup({ op: 'and', args: [] })).toBe(true)
    expect(isComparison({ op: '<=', left: 1, right: 2 })).toBe(true)
    expect(isComparison({ fn: 'all' })).toBe(false)
    expect(operands({ op: 'exists', arg: 1 })).toEqual([1])
    expect(operands({ op: '+', args: [1, 2] })).toEqual([1, 2])
  })

  it('parses typed literals', () => {
    expect(parseLiteral('60')).toBe(60)
    expect(parseLiteral('true')).toBe(true)
    expect(parseLiteral('null')).toBeNull()
    expect(parseLiteral('FIN')).toBe('FIN')
    expect(parseLiteral('007', ['string'])).toBe('007')
    expect(literalText(null)).toBe('')
    expect(literalText(3)).toBe('3')
    expect(literalText([1])).toBe('[1]')
  })

  it('toggles NOT', () => {
    const c = { op: '==', left: 1, right: 1 }
    expect(toggleNot(c)).toEqual({ op: 'not', arg: c })
    expect(toggleNot(toggleNot(c))).toEqual(c)
  })
})

describe('typing values', () => {
  it('reads decimals while they are typed', () => {
    // "3." is an intermediate state of "3.5": the box keeps the text, the value is 3 (UI-01)
    expect(parseLiteral('3.')).toBe(3)
    expect(parseLiteral('3.5')).toBe(3.5)
    expect(parseLiteral('-0.25')).toBe(-0.25)
    expect(parseLiteral('.5')).toBe(0.5)
    expect(parseLiteral('1e3')).toBe(1000)
  })

  it('keeps as text what only JavaScript reads as a number', () => {
    expect(parseLiteral('0x10')).toBe('0x10')
    expect(parseLiteral('Infinity')).toBe('Infinity')
    expect(parseLiteral(' ')).toBe(' ')
  })

  it('accepts a decimal comma for numeric fields only', () => {
    expect(parseLiteral('3,5', ['number'])).toBe(3.5)
    expect(parseLiteral('3,5', ['integer'])).toBe(3.5)
    expect(parseLiteral('3,5')).toBe('3,5')
    expect(parseLiteral('20100', ['string'])).toBe('20100')
  })
})

describe('typing lists', () => {
  it('splits on commas, numbers only for numeric fields (UI-08)', async () => {
    const { parseList } = await import('./expr')
    expect(parseList('IT, FR,', false)).toEqual(['IT', 'FR'])
    expect(parseList('1, 2.5, x', true)).toEqual([1, 2.5, 'x'])
    expect(parseList('20100, 0x10', false)).toEqual(['20100', '0x10'])
  })
})
