import { describe, expect, it } from 'vitest'

import { describeTypes, elementSchema, listFields } from './schemaPaths'

const schema = {
  type: 'object',
  required: ['student'],
  $defs: { course: { type: 'object', properties: { cfu: { type: 'integer' }, area: { enum: ['FIN', 'STR'], type: 'string' } } } },
  properties: {
    student: { type: 'object', properties: { birthDate: { type: 'string', format: 'date' } } },
    courses: { type: 'array', items: { $ref: '#/$defs/course' } },
    note: { anyOf: [{ type: 'string' }, { type: 'null' }] },
    'odd key': { type: 'number' },
  },
}

describe('schema field listing', () => {
  it('lists nested fields alphabetically with types and references', () => {
    const fields = listFields(schema)
    expect(fields.map((f) => f.path)).toEqual([
      '$.input.courses',
      '$.input.courses[*].area',
      '$.input.courses[*].cfu',
      '$.input.note',
      '$.input["odd key"]',
      '$.input.student',
      '$.input.student.birthDate',
    ])
    const cfu = fields.find((f) => f.name === 'cfu')
    if (!cfu) throw new Error('cfu missing')
    expect(cfu).toMatchObject({ many: true, types: ['integer'], depth: 1 })
    expect(fields.find((f) => f.name === 'area')?.enum).toEqual(['FIN', 'STR'])
    expect(fields.find((f) => f.name === 'student')?.required).toBe(true)
    expect(fields.find((f) => f.name === 'note')?.types).toEqual(['string', 'null'])
    expect(describeTypes(cfu)).toBe('lista di integer')
    expect(describeTypes(fields.find((f) => f.name === 'birthDate') ?? { types: [], many: false })).toBe('string (date)')
    expect(listFields(undefined)).toEqual([])
  })

  it('finds the element schema of arrays for aggregates', () => {
    const el = elementSchema(schema, '$.input.courses')
    expect(listFields(el, '$.item').map((f) => f.path)).toEqual(['$.item.area', '$.item.cfu'])
    expect(elementSchema(schema, '$.input.student')).toBeUndefined()
    expect(elementSchema(schema, '$.vars.x')).toBeUndefined()
    expect(elementSchema(undefined, '$.input.courses')).toBeUndefined()
  })
})
