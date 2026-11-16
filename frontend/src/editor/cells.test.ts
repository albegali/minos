import { describe, expect, it } from 'vitest'

import { formatCell, formatOutput, formatValue, parseCell, parseOutput, parseValue } from './cells'

describe('decision table cells', () => {
  it.each([
    ['', null],
    ['-', null],
    ['EMBA', 'EMBA'],
    ['60', 60],
    ['true', true],
    ['"007"', '007'],
    ['= 5', 5],
    ['MERIT, NEED', ['MERIT', 'NEED']],
    ['"a, b", c', ['a, b', 'c']],
    ['>= 60', { op: '>=', value: 60 }],
    ['<5', { op: '<', value: 5 }],
    ['!= X', { op: '!=', value: 'X' }],
    ['!= A, B', { op: 'not_in', value: ['A', 'B'] }],
    ['30..59', { op: 'between', value: [30, 59] }],
    ['[1 .. 5]', { op: 'between', value: [1, 5] }],
    ['2027-01-01..2027-12-31', { op: 'date_between', value: ['2027-01-01', '2027-12-31'] }],
    ['< 2027-01-01', { op: 'date_before', value: '2027-01-01' }],
    ['> 2027-01-01', { op: 'date_after', value: '2027-01-01' }],
    ['>= $.vars.min', { op: '>=', value: { ref: '$.vars.min' } }],
    ['$.vars.min', { ref: '$.vars.min' }],
  ])('parses %j', (text, cell) => {
    expect(parseCell(text)).toEqual(cell)
  })

  it.each([
    [null, ''],
    ['EMBA', 'EMBA'],
    ['007', '"007"'],
    ['a, b', '"a, b"'],
    [['MERIT', 'NEED'], 'MERIT, NEED'],
    [{ op: '>=', value: 60 }, '>= 60'],
    [{ op: 'between', value: [30, 59] }, '30..59'],
    [{ op: 'date_between', value: ['2027-01-01', '2027-12-31'] }, '2027-01-01..2027-12-31'],
    [{ op: 'not_in', value: ['A', 'B'] }, '!= A, B'],
    [{ op: 'in', value: ['A'] }, 'A'],
    [{ op: 'date_before', value: '2027-01-01' }, '< 2027-01-01'],
    [{ op: 'date_after', value: '2027-01-01' }, '> 2027-01-01'],
    [{ op: '==', value: 3 }, '3'],
    [{ op: 'contains', value: 'x' }, 'contains x'],
    [{ ref: '$.vars.min' }, '$.vars.min'],
  ])('formats %j', (cell, text) => {
    expect(formatCell(cell)).toBe(text)
  })

  it('round-trips what it formats', () => {
    const cells = [null, 'EMBA', 60, ['A', 'B'], { op: '<=', value: 3 }, { op: 'between', value: [1, 2] }, '007', '>= x']
    for (const c of cells) expect(parseCell(formatCell(c))).toEqual(c)
  })

  it('handles values and outputs', () => {
    expect(parseValue('null')).toBeNull()
    expect(formatValue(null)).toBe('null')
    expect(formatValue({ fn: 'x' })).toBe('{"fn":"x"}')
    expect(formatValue('')).toBe('""')
    expect(parseOutput('38500')).toBe(38500)
    expect(parseOutput('$.input.x')).toEqual({ ref: '$.input.x' })
    expect(formatOutput({ op: '+', args: [1, 2] })).toBe('{"op":"+","args":[1,2]}')
    expect(formatOutput(undefined)).toBe('')
    expect(formatOutput({ ref: '$.a' })).toBe('$.a')
  })
})
