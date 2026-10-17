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
  /**
   * Whether `params` fill every placeholder of the key's message, the plural count included. A
   * message built from server data checks this first, because a server older or newer than the
   * page can leave out a param, and production fills a missing one with nothing.
   */
  fills: (key: string, params?: MessageParams) => boolean
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
const PLACEHOLDER_NAMES = /\{(\w+)\}/g
/**
 * A `{placeholder}` left in text a person reads, the translator's or one a filled-in value brought.
 * `${NAME}` and `{{NAME}}` in a configuration example are another tool's variables, not placeholders.
 */
export const UNFILLED = /(?<![${])\{(\w+)\}(?!\})/
const warned = new Set<string>()

/** The names of the placeholders in `text`, such as "count" in "{count} rules". */
function placeholders(text: string): string[] {
  return Array.from(text.matchAll(PLACEHOLDER_NAMES), (match) => match[1] ?? "")
}

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

  /** The form of a plural message `count` selects, or null when `count` is not a number. */
  function selected(message: PluralMessage, count: MessageParams[string] | undefined): string | null {
    return typeof count === "number" ? (message[plurals.select(count)] ?? message.other) : null
  }

  function template(key: string, message: Message, params: MessageParams): string {
    if (typeof message === "string") return message
    const text = selected(message, params.count)
    if (text === null) report(key, "plural message needs a numeric count")
    return text ?? message.other
  }

  /** `text` with its placeholders filled; a missing one is left out, so its braces never show. */
  function fill(key: string, text: string, params: MessageParams): string {
    return text
      .split(PLACEHOLDER)
      .map((part) => {
        const name = /^\{(\w+)\}$/.exec(part)?.[1]
        if (!name) return transform ? transform(part) : part
        const value = params[name]
        if (value === undefined) {
          report(key, `missing parameter {${name}}`)
          return ""
        }
        return typeof value === "number" ? numbers.format(value) : value
      })
      .join("")
  }

  function t(key: MessageKey, params: MessageParams = {}): string {
    const message = resolve(key)
    if (message === undefined) {
      report(key, "missing message")
      return key
    }
    const text = fill(key, template(key, message, params), params)
    // Under test, a value that still holds a placeholder, such as server text, fails too.
    const unfilled = import.meta.env.MODE === "test" ? UNFILLED.exec(text) : null
    if (unfilled) report(key, `unfilled placeholder ${unfilled[0]}`)
    return text
  }

  const has = (key: string): key is MessageKey => resolve(key) !== undefined

  function fills(key: string, params: MessageParams = {}): boolean {
    const message = resolve(key)
    if (message === undefined) return false
    const text = typeof message === "string" ? message : selected(message, params.count)
    return text !== null && placeholders(text).every((name) => params[name] !== undefined)
  }

  return { locale, formatLocale, t, has, fills, format: createFormatters(formatLocale, t, locale) }
}
