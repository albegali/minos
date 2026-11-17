// Helpers over the expression AST (see docs/rgd-format.md).

import { type Key, t } from '../i18n'

export type Expr = unknown

export interface RefExpr {
  ref: string
}
export interface OpExpr {
  op: string
  left?: Expr
  right?: Expr
  arg?: Expr
  args?: Expr[]
}
export interface FnExpr {
  fn: string
  args?: Expr[]
  where?: Expr
  select?: Expr
}

const isObject = (e: Expr): e is Record<string, unknown> =>
  typeof e === 'object' && e !== null && !Array.isArray(e)

export const isRef = (e: Expr): e is RefExpr => isObject(e) && typeof e.ref === 'string'
export const isOp = (e: Expr): e is OpExpr => isObject(e) && typeof e.op === 'string'
export const isFn = (e: Expr): e is FnExpr => isObject(e) && typeof e.fn === 'string'
export const isLiteral = (e: Expr): boolean =>
  e === null || ['string', 'number', 'boolean'].includes(typeof e) || (isObject(e) && 'literal' in e)

export const LOGIC = new Set(['and', 'or'])
export const RANGE = new Set(['between', 'date_between'])
export const UNARY = new Set(['exists', 'is_null', 'is_not_null'])
export const COMPARE = new Set([
  '==', '!=', '<', '<=', '>', '>=', 'in', 'not_in', 'contains', 'starts_with', 'ends_with',
  'regex', 'date_before', 'date_after', ...RANGE, ...UNARY,
])

export function blankComparison(): OpExpr {
  return { op: '==', left: { ref: '' }, right: '' }
}

/** Operands as a list, whatever the spelling (left/right, arg, args). */
export function operands(e: OpExpr): Expr[] {
  if (Array.isArray(e.args)) return e.args
  const out: Expr[] = []
  if ('left' in e) out.push(e.left)
  if ('right' in e) out.push(e.right)
  if ('arg' in e) out.push(e.arg)
  return out
}

export const isGroup = (e: Expr): e is OpExpr => isOp(e) && LOGIC.has(e.op)
export const isNot = (e: Expr): e is OpExpr => isOp(e) && e.op === 'not'
export const isComparison = (e: Expr): e is OpExpr => isOp(e) && COMPARE.has(e.op)

const SYMBOL: Record<string, string> = {
  '==': '=', '!=': '≠', '<': '<', '<=': '≤', '>': '>', '>=': '≥', in: 'in', regex: '~',
  '+': '+', '-': '−', '*': '×', '/': '÷',
}
/** Operators rendered as words, translated (`expr.<op>`). */
const WORDS: Record<string, Key> = {
  not_in: 'expr.not_in', contains: 'expr.contains', starts_with: 'expr.starts_with',
  ends_with: 'expr.ends_with', date_before: 'expr.date_before', date_after: 'expr.date_after',
  between: 'expr.between', date_between: 'expr.date_between', exists: 'expr.exists',
  is_null: 'expr.is_null', is_not_null: 'expr.is_not_null', '%': 'expr.mod',
}

function symbol(op: string): string {
  const word = WORDS[op]
  return word ? t(word) : (SYMBOL[op] ?? op)
}

export function shortRef(path: string): string {
  return path.replace(/^\$\.input\./, '').replace(/^\$\./, '')
}

/** Compact, human-readable rendering used on canvas nodes and in lists. */
export function describe(e: Expr, depth = 0): string {
  if (depth > 4) return '…'
  if (isRef(e)) return e.ref ? shortRef(e.ref) : '?'
  if (isFn(e)) {
    const args = (e.args ?? []).map((a) => describe(a, depth + 1)).join(', ')
    const where = e.where !== undefined ? ` ${t('expr.where')} ${describe(e.where, depth + 1)}` : ''
    const select = e.select !== undefined ? ` ${t('expr.of')} ${describe(e.select, depth + 1)}` : ''
    return `${e.fn}(${args}${select}${where})`
  }
  if (isOp(e)) {
    const ops = operands(e)
    if (LOGIC.has(e.op)) {
      const joined = ops.map((o) => describe(o, depth + 1)).join(` ${t(e.op === 'and' ? 'expr.and' : 'expr.or')} `)
      return depth > 0 ? `(${joined})` : joined
    }
    if (e.op === 'not') return `${t('expr.not')} ${describe(ops[0], depth + 1)}`
    if (UNARY.has(e.op)) return `${describe(ops[0], depth + 1)} ${symbol(e.op)}`
    if (RANGE.has(e.op) && Array.isArray(ops[1])) {
      const [lo, hi] = ops[1] as Expr[]
      return t('expr.range', {
        value: describe(ops[0], depth + 1),
        low: describe(lo, depth + 1),
        high: describe(hi, depth + 1),
      })
    }
    if (e.op === 'if') return t('expr.if', { condition: describe(ops[0], depth + 1) })
    return ops.map((o) => describe(o, depth + 1)).join(` ${symbol(e.op)} `)
  }
  if (Array.isArray(e)) return `[${e.map((x) => describe(x, depth + 1)).join(', ')}]`
  if (isObject(e) && 'literal' in e) return JSON.stringify(e.literal)
  if (typeof e === 'string') return `"${e}"`
  return String(e)
}

/** Parse what a user typed in a value box: numbers and booleans as such, the rest as text. */
export function parseLiteral(text: string, preferred?: string[]): Expr {
  const t = text.trim()
  if (preferred?.includes('string') && !preferred.includes('number')) return text
  if (t === 'true' || t === 'false') return t === 'true'
  if (t === 'null') return null
  if (t !== '' && !Number.isNaN(Number(t))) return Number(t)
  return text
}

export function literalText(e: Expr): string {
  if (e === null || e === undefined) return ''
  if (typeof e === 'string') return e
  if (typeof e === 'number' || typeof e === 'boolean') return String(e)
  return JSON.stringify(e)
}

/** Wrap or unwrap a NOT around an expression. */
export function toggleNot(e: Expr): Expr {
  if (isNot(e)) return operands(e)[0]
  return { op: 'not', arg: e }
}
