import { isPluralMessage } from "./translator"
import { PLURAL_CATEGORIES, type Catalog, type Message, type PluralCategory } from "./types"

const PRODUCT = "Calendar Ghost"
const EM_DASH = "\u2014"
const PLACEHOLDER = /\{(\w+)\}/g

function placeholdersOf(message: Message): Set<string> {
  const forms = typeof message === "string" ? [message] : Object.values(message).filter((form): form is string => typeof form === "string")
  const names = new Set(forms.flatMap((form) => [...form.matchAll(PLACEHOLDER)].flatMap((match) => (match[1] ? [match[1]] : []))))
  if (typeof message !== "string") names.add("count")
  return names
}

function forms(message: Message): string[] {
  return typeof message === "string" ? [message] : Object.values(message).filter((form): form is string => typeof form === "string")
}

function messages(catalog: Catalog, prefix = "", problems: string[] = []): Map<string, Message> {
  const found = new Map<string, Message>()
  for (const [key, node] of Object.entries(catalog)) {
    const path = `${prefix}${key}`
    if (typeof node === "string" || isPluralMessage(node)) {
      const categories = typeof node === "string" ? [] : Object.keys(node)
      if (typeof node !== "string" && categories.some((category) => !PLURAL_CATEGORIES.includes(category as PluralCategory))) {
        problems.push(`${path}: a group may not use the key other`)
        continue
      }
      found.set(path, node)
    } else {
      for (const [inner, message] of messages(node, `${path}.`, problems)) found.set(inner, message)
    }
  }
  return found
}

const describeSet = (names: Set<string>) => [...names].sort().map((name) => `{${name}}`).join(" ")

/** The plural forms `locale` needs that a translated plural message leaves out. */
function pluralProblems(key: string, original: Message, translated: Message, required: PluralCategory[]): string[] {
  if (typeof original === "string" || typeof translated === "string") return []
  const missing = required.filter((category) => translated[category] === undefined)
  return missing.length ? [`${key}: missing plural forms ${missing.join(" ")}`] : []
}

/** What keeps one translated message from matching its English original. */
function messageProblems(key: string, original: Message, translated: Message, required: PluralCategory[]): string[] {
  const texts = forms(translated)
  if (texts.some((text) => text.trim() === "")) return [`${key}: empty`]
  const problems: string[] = []
  if (forms(original).some((text) => text.includes(PRODUCT)) && !texts.some((text) => text.includes(PRODUCT))) {
    problems.push(`${key}: drops ${PRODUCT}`)
  }
  if (texts.some((text) => text.includes(EM_DASH))) problems.push(`${key}: uses an em dash`)
  const expected = placeholdersOf(original)
  const actual = placeholdersOf(translated)
  if (describeSet(expected) !== describeSet(actual)) {
    problems.push(`${key}: placeholders ${describeSet(actual)} differ from English ${describeSet(expected)}`)
  }
  return [...problems, ...pluralProblems(key, original, translated, required)]
}

/** What keeps `other` from being a faithful translation of `english` for `locale`. */
export function catalogProblems(english: Catalog, other: Catalog, locale: string): string[] {
  const problems: string[] = []
  const source = messages(english, "", problems)
  const target = messages(other, "", problems)
  const required = new Intl.PluralRules(locale).resolvedOptions().pluralCategories as PluralCategory[]
  for (const [key, original] of source) {
    const translated = target.get(key)
    if (translated === undefined) problems.push(`${key}: missing`)
    else problems.push(...messageProblems(key, original, translated, required))
  }
  for (const key of target.keys()) if (!source.has(key)) problems.push(`${key}: not in English`)
  return [...new Set(problems)]
}
