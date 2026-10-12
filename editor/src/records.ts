/**
 * Lookups keyed by names that come from a bibliography.
 *
 * Citation keys, group names and field names are the file's text, and
 * `constructor`, `toString` or `__proto__` is as valid a citation key as
 * `Newton1687`. A plain object literal inherits those names from
 * `Object.prototype`, so `index[key] ??= []` on one would find a function
 * instead of creating the entry, and the whole read would fail. Every map keyed
 * by such a name is built with `record()` and read with `own()`.
 */

/** An empty map with no prototype, so no key is ever already "present". */
export function record<T>(): Record<string, T> {
  return Object.create(null) as Record<string, T>;
}

/** The value stored under `key` itself, never one inherited from a prototype. */
export function own<T>(map: Readonly<Record<string, T>> | null | undefined, key: string): T | undefined {
  return map != null && Object.prototype.hasOwnProperty.call(map, key) ? map[key] : undefined;
}
