import { describe, expect, it } from 'vitest'

import { applyRefRows, entityOf, refRows, unpinRefs } from './entityRefs'
import { listFields } from './schemaPaths'

const authored = {
  type: 'object',
  required: ['student'],
  properties: {
    student: { $ref: 'entity:Student@2', description: 'who' },
    courses: { type: 'array', items: { $ref: 'entity:Course@1' } },
    note: { type: 'string', enum: [{ $ref: 'entity:Data@1' }] },
  },
}

describe('entity references', () => {
  it('recognises authored and resolved references', () => {
    expect(entityOf({ $ref: 'entity:Course' })).toEqual({ entity: 'Course' })
    expect(entityOf({ $ref: 'entity:Course@3' })).toEqual({ entity: 'Course', version: 3 })
    expect(entityOf({ $ref: '#/$defs/entity:Course@3' })).toEqual({ entity: 'Course', version: 3 })
    expect(entityOf({ $ref: '#/$defs/course' })).toBeUndefined()
    expect(entityOf({ type: 'string' })).toBeUndefined()
  })

  it('unpins every reference, leaving data alone', () => {
    const out = unpinRefs(authored) as typeof authored
    expect(out.properties.student).toEqual({ $ref: 'entity:Student', description: 'who' })
    expect(out.properties.courses.items).toEqual({ $ref: 'entity:Course' })
    expect(out.properties.note.enum).toEqual([{ $ref: 'entity:Data@1' }])
    expect(authored.properties.student.$ref).toBe('entity:Student@2')
  })

  it('reads and writes the entity-typed fields, keeping the others', () => {
    expect(refRows(authored)).toEqual([
      { name: 'student', entity: 'Student', many: false, required: true, ref: 'entity:Student@2' },
      { name: 'courses', entity: 'Course', many: true, required: false, ref: 'entity:Course@1' },
    ])
    const out = applyRefRows(authored, [
      { name: 'student', entity: 'Student', many: false, required: true, ref: 'entity:Student@2' },
      { name: 'courses', entity: 'Program', many: false, required: true, ref: 'entity:Course@1' },
      { name: ' ', entity: 'Course', many: false, required: true },
    ]) as Record<string, unknown>
    expect(out.properties).toEqual({
      student: { $ref: 'entity:Student@2' },
      courses: { $ref: 'entity:Program' },
      note: authored.properties.note,
    })
    expect(out.required).toEqual(['courses', 'student'])
    const empty = applyRefRows(undefined, []) as Record<string, unknown>
    expect(empty).toEqual({ type: 'object', properties: {} })
  })

  it('shows which entity a field comes from', () => {
    const resolved = {
      type: 'object',
      properties: {
        program: { $ref: '#/$defs/entity:Program@1' },
        courses: { type: 'array', items: { $ref: '#/$defs/entity:Course@1' } },
      },
      $defs: {
        'entity:Program@1': { type: 'object', properties: { code: { type: 'string' } } },
        'entity:Course@1': { type: 'object', properties: { cfu: { type: 'integer' } } },
      },
    }
    const fields = listFields(resolved)
    expect(fields.map((f) => [f.path, f.entity?.entity])).toEqual([
      ['$.input.courses', 'Course'],
      ['$.input.courses[*].cfu', undefined],
      ['$.input.program', 'Program'],
      ['$.input.program.code', undefined],
    ])
  })
})

describe('keyword-named properties', () => {
  it('unpins references under a property called "default" (ENG-11)', () => {
    const out = unpinRefs({ type: 'object', properties: { default: { $ref: 'entity:Course@2' } } }) as {
      properties: { default: unknown }
    }
    expect(out.properties.default).toEqual({ $ref: 'entity:Course' })
  })
})

describe('reference grammar', () => {
  it('matches the backend (CQ-06)', () => {
    expect(entityOf({ $ref: 'entity:Course@0' })).toBeUndefined()
    expect(entityOf({ $ref: `entity:${'a'.repeat(101)}` })).toBeUndefined()
    expect(entityOf({ $ref: `entity:${'a'.repeat(100)}@12` })).toEqual({ entity: 'a'.repeat(100), version: 12 })
  })
})
