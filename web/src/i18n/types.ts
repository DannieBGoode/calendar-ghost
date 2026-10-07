import type english from "./locales/en"

export type PluralCategory = "zero" | "one" | "two" | "few" | "many" | "other"
export const PLURAL_CATEGORIES: readonly PluralCategory[] = ["zero", "one", "two", "few", "many", "other"]
export type PluralMessage = Partial<Record<PluralCategory, string>> & { other: string }
export type Message = string | PluralMessage
// An index signature, because a recursive type cannot be a Record (TS2456).
export type Catalog = { [key: string]: Message | Catalog }
export type MessageParams = Readonly<Record<string, string | number>>

type Leaves<T, Prefix extends string = ""> = {
  [K in keyof T & string]: T[K] extends string
    ? `${Prefix}${K}`
    : T[K] extends { other: string }
      ? `${Prefix}${K}`
      : Leaves<T[K], `${Prefix}${K}.`>
}[keyof T & string]

/** Every message key in the English catalog, so a mistyped key fails the typecheck. */
export type MessageKey = Leaves<typeof english>
