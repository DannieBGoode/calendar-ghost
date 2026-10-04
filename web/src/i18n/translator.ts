import english from "./locales/en"
import { createFormatters, type Formatters } from "./format"
import type { Catalog, Message, MessageKey, MessageParams, PluralMessage } from "./types"

export type I18n = {
  /** The UI language, such as "en"; `<html lang>` and plural rules use it. */
  locale: string
  /** The tag formats use, such as "en-GB" when the browser prefers it (see `resolveFormatLocale`). */
  formatLocale: string
  t: (key: MessageKey, params?: MessageParams) => string
  /** Whether a key built from server data, such as an error code, has a message. */
  has: (key: string) => key is MessageKey
  format: Formatters
}

type Options = {
  locale: string
  formatLocale?: string
  catalog: Catalog
  fallback?: Catalog
  /** Rewrites the literal text of every template, leaving placeholders; the pseudo-locale uses it. */
  transform?: ((template: string) => string) | undefined
}

const PLACEHOLDER = /(\{\w+\})/
const warned = new Set<string>()

export function isPluralMessage(node: unknown): node is PluralMessage {
  return typeof node === "object" && node !== null && typeof (node as PluralMessage).other === "string"
}

function lookup(catalog: Catalog, key: string): Message | undefined {
  let node: Message | Catalog | undefined = catalog
  for (const part of key.split(".")) {
    if (node === undefined || typeof node === "string" || isPluralMessage(node)) return undefined
    node = node[part]
  }
  return typeof node === "string" || isPluralMessage(node) ? node : undefined
}

/** Under test a broken message fails loudly; in production it degrades and warns once. */
function report(key: string, problem: string): void {
  if (import.meta.env.MODE === "test") throw new Error(`i18n "${key}": ${problem}`)
  const id = `${key}:${problem}`
  if (warned.has(id)) return
  warned.add(id)
  console.warn(`i18n "${key}": ${problem}`)
}

export function createI18n({ locale, formatLocale = locale, catalog, fallback = english, transform }: Options): I18n {
  const plurals = new Intl.PluralRules(locale)
  const numbers = new Intl.NumberFormat(formatLocale)
  const resolve = (key: string) => lookup(catalog, key) ?? lookup(fallback, key)

  function template(key: string, message: Message, params: MessageParams): string {
    if (typeof message === "string") return message
    const count = params.count
    if (typeof count !== "number") {
      report(key, "plural message needs a numeric count")
      return message.other
    }
    return message[plurals.select(count)] ?? message.other
  }

  function t(key: MessageKey, params: MessageParams = {}): string {
    const message = resolve(key)
    if (message === undefined) {
      report(key, "missing message")
      return key
    }
    return template(key, message, params)
      .split(PLACEHOLDER)
      .map((part) => {
        const name = /^\{(\w+)\}$/.exec(part)?.[1]
        if (!name) return transform ? transform(part) : part
        const value = params[name]
        if (value === undefined) {
          report(key, `missing parameter {${name}}`)
          return part
        }
        return typeof value === "number" ? numbers.format(value) : value
      })
      .join("")
  }

  const has = (key: string): key is MessageKey => resolve(key) !== undefined
  return { locale, formatLocale, t, has, format: createFormatters(formatLocale, t, locale) }
}
