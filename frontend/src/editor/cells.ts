// Text syntax for decision table cells, close to DMN unary tests, so that a table can be
// filled like a spreadsheet:
//
//   (empty) or -          any value                      -> null
//   EMBA  /  60  /  true  equals                          -> "EMBA" / 60 / true
//   "007"                 equals the text (quotes keep it a string)
//   MERIT, NEED           one of                          -> ["MERIT", "NEED"]
//   != X  /  != A, B      differs / none of               -> {op: "!=" | "not_in", value}
//   >= 60, < 5, > x, <= y comparison                      -> {op, value}
//   30..59                range, ends included            -> {op: "between", value: [30, 59]}
//   2027-01-01..2027-12-31   date range                   -> {op: "date_between", ...}
//   < 2027-01-01          before / after a date           -> {op: "date_before" | "date_after"}
//   $.vars.min            the value of a reference        -> {ref: "$.vars.min"}
//
// formatCell() is the inverse, used to display stored cells.

export type Cell = unknown

const DATE = /^\d{4}-\d{2}-\d{2}([T ][\d:.]+(Z|[+-]\d{2}:?\d{2})?)?$/
// Plain decimal numbers: "0x10" or "Infinity" stay text.
const NUMBER = /^-?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/

/** A cell holding a JSON object (an expression, shown as JSON): kept whole, never split on its
 * commas. */
function jsonObject(text: string): Record<string, unknown> | undefined {
  if (!text.startsWith('{')) return undefined
  try {
    const parsed: unknown = JSON.parse(text)
    return parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : undefined
  } catch {
    return undefined
  }
}

/** A single value: number, boolean, null, quoted text, reference, or bare text. */
export function parseValue(text: string): unknown {
  const t = text.trim()
  if (t.startsWith('$.')) return { ref: t }
  if (t.length >= 2 && t.startsWith('"') && t.endsWith('"')) return t.slice(1, -1)
  if (t === 'true' || t === 'false') return t === 'true'
  if (t === 'null') return null
  if (NUMBER.test(t)) return Number(t)
  return t
}

function splitList(text: string): string[] {
  const out: string[] = []
  let current = ''
  let quoted = false
  for (const ch of text) {
    if (ch === '"') quoted = !quoted
    if (ch === ',' && !quoted) {
      out.push(current)
      current = ''
    } else {
      current += ch
    }
  }
  out.push(current)
  return out.map((s) => s.trim()).filter((s) => s !== '')
}

const isDate = (v: unknown) => typeof v === 'string' && DATE.test(v)

export function parseCell(text: string): Cell {
  const t = text.trim()
  if (t === '' || t === '-') return null
  const object = jsonObject(t)
  if (object) return object

  const cmp = /^(>=|<=|!=|=|<|>)\s*(.+)$/.exec(t)
  if (cmp) {
    const op = cmp[1] as string
    const rest = cmp[2] as string
    if (op === '!=' && splitList(rest).length > 1) {
      return { op: 'not_in', value: splitList(rest).map(parseValue) }
    }
    const value = parseValue(rest)
    if (op === '=') return value
    if (isDate(value) && (op === '<' || op === '>')) {
      return { op: op === '<' ? 'date_before' : 'date_after', value }
    }
    return { op, value }
  }

  const range = /^\[?\s*([^\]]+?)\s*\.\.\s*([^\]]+?)\s*\]?$/.exec(t)
  if (range && !t.startsWith('"')) {
    const lo = parseValue(range[1] as string)
    const hi = parseValue(range[2] as string)
    return { op: isDate(lo) && isDate(hi) ? 'date_between' : 'between', value: [lo, hi] }
  }

  const items = splitList(t)
  if (items.length > 1) return items.map(parseValue)
  return parseValue(t)
}

/** Text of a single value, quoting strings that would otherwise parse as something else. */
export function formatValue(v: unknown): string {
  if (v === null) return 'null'
  if (typeof v === 'object' && v !== null && 'ref' in v) return String((v as { ref: unknown }).ref)
  if (typeof v === 'string') {
    const reparsed = parseValue(v)
    const ambiguous = reparsed !== v || /[,]|\.\./.test(v) || /^(>=|<=|!=|=|<|>|-$)/.test(v)
    return ambiguous || v === '' ? `"${v}"` : v
  }
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

export function formatCell(cell: Cell): string {
  if (cell === null || cell === undefined || cell === '-') return ''
  if (Array.isArray(cell)) return cell.map(formatValue).join(', ')
  if (typeof cell === 'object' && 'op' in cell && 'value' in cell) {
    const { op, value } = cell as { op: string; value: unknown }
    switch (op) {
      case 'between':
      case 'date_between': {
        const [lo, hi] = Array.isArray(value) ? value : [value, value]
        return `${formatValue(lo)}..${formatValue(hi)}`
      }
      case 'not_in':
        return `!= ${(Array.isArray(value) ? value : [value]).map(formatValue).join(', ')}`
      case 'in':
        return (Array.isArray(value) ? value : [value]).map(formatValue).join(', ')
      case 'date_before':
        return `< ${formatValue(value)}`
      case 'date_after':
        return `> ${formatValue(value)}`
      case '==':
        return formatValue(value)
      default:
        return `${op} ${formatValue(value)}`
    }
  }
  return formatValue(cell)
}

/** Output cells: a value or a reference; anything else is kept as an expression. */
export function parseOutput(text: string): unknown {
  return jsonObject(text.trim()) ?? parseValue(text)
}

export function formatOutput(v: unknown): string {
  if (typeof v === 'object' && v !== null && !('ref' in v)) return JSON.stringify(v)
  return v === undefined ? '' : formatValue(v)
}
