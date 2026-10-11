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

/**
 * The values each key template takes, keyed by the template with each `${...}` written as `*`,
 * such as `people.overview.next.*.self`. "server" marks a template the server's codes complete,
 * so every key it matches counts as named.
 */
export type TemplateValues = Readonly<Record<string, readonly string[] | "server">>

const QUOTED = /(["'`])([A-Za-z]\w*(?:\.\w+)+)\1/g
const TEMPLATE_LITERAL = /`([^`]*\$\{[^`]*)`/g
const EXPRESSION = /\$\{[^}]*\}/g

/** Each `*` of `template` replaced by each of `values`, in every combination. */
function expand(template: string, values: readonly string[]): string[] {
  if (!template.includes("*")) return [template]
  return values.flatMap((value) => expand(template.replace("*", value), values))
}

function matcher(template: string): RegExp {
  return new RegExp(`^${template.replaceAll(".", "\\.").replaceAll("*", "[^.]+")}$`)
}

/** The key templates the sources build, such as `people.cause.*`, within the catalog's namespaces. */
function keyTemplates(sources: readonly string[], namespaces: Set<string>): Set<string> {
  const found = new Set<string>()
  for (const source of sources) {
    for (const [, text = ""] of source.matchAll(TEMPLATE_LITERAL)) {
      const template = text.replace(EXPRESSION, "*")
      if (/^[\w.*]+$/.test(template) && namespaces.has(template.split(".")[0] ?? "")) found.add(template)
    }
  }
  return found
}

/** What the sources name: their literal keys and every key a template's values complete. */
function namedKeys(keys: string[], sources: readonly string[], templates: Set<string>, values: TemplateValues): Set<string> {
  const named = new Set(sources.flatMap((source) => [...source.matchAll(QUOTED)].map((match) => match[2] ?? "")))
  for (const template of templates) {
    const known = values[template]
    if (known === "server") for (const key of keys.filter((each) => matcher(template).test(each))) named.add(key)
    else for (const key of expand(template, known ?? [])) named.add(key)
  }
  return named
}

/** English keys no source names, and key templates whose values are unknown or unused. */
export function unusedKeys(english: Catalog, sources: readonly string[], values: TemplateValues): string[] {
  const keys = [...messages(english).keys()]
  const templates = keyTemplates(sources, new Set(Object.keys(english)))
  const named = namedKeys(keys, sources, templates, values)
  return [
    ...keys.filter((key) => !named.has(key)).map((key) => `${key}: unused`),
    ...[...templates].filter((template) => !(template in values)).map((template) => `${template}: a key template without known values`),
    ...Object.keys(values)
      .filter((template) => !templates.has(template))
      .map((template) => `${template}: known values for a key template no source builds`),
  ]
}
