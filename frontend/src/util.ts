/** Copy of `obj` without `key` (avoids `delete` on computed keys). */
export function omit<T extends Record<string, unknown>>(obj: T, key: string): T {
  return Object.fromEntries(Object.entries(obj).filter(([k]) => k !== key)) as T
}

/** Copy of `obj` without the keys whose value is `undefined`. */
export function compact<T extends Record<string, unknown>>(obj: T): T {
  return Object.fromEntries(Object.entries(obj).filter(([, v]) => v !== undefined)) as T
}
