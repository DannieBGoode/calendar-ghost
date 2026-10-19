import english from "./locales/en"
import { isPluralMessage, UNFILLED } from "./translator"
import type { Catalog } from "./types"

/**
 * Words a person must never read: a `{placeholder}` nobody filled, or a catalog key shown in place
 * of its message. The Vitest setup (`src/test-setup.ts`) watches every page a test renders for
 * them and fails the test that shows one, whatever put it there: the translator, a component, or
 * server text.
 */

const PLACEHOLDERS = new RegExp(UNFILLED.source, "g")
/** Words joined by dots, such as `people.plans.status.administrators` or `calendar.google.com`. */
const DOTTED = /\b[A-Za-z]\w*(?:\.\w+)+\b/g
const TEXT_ATTRIBUTES = ["aria-label", "aria-description", "aria-valuetext", "aria-roledescription", "alt", "placeholder", "title"]

/** Whether `path` begins inside the English catalog, such as `people.plans.…`, so it is a key, known or not. */
function isCatalogPath(path: string): boolean {
  const [namespace = "", group = ""] = path.split(".")
  const node = Object.hasOwn(english, namespace) ? (english as Catalog)[namespace] : undefined
  return node !== undefined && typeof node !== "string" && !isPluralMessage(node) && Object.hasOwn(node, group)
}

function matches(text: string): RegExpExecArray[] {
  const keys = [...text.matchAll(DOTTED)].filter(([path]) => isCatalogPath(path))
  return [...text.matchAll(PLACEHOLDERS), ...keys]
}

/** The unfilled placeholders and catalog keys in `text`, placeholders first. */
export function unfilledText(text: string): string[] {
  return matches(text).map(([match]) => match)
}

/** Each unfilled placeholder or key in `text` with a few words either side, to find it by. */
function inContext(text: string): string[] {
  return matches(text).map(({ 0: match, index }) => text.slice(Math.max(0, index - 40), index + match.length + 40).trim())
}

/** What holds unfilled words under `node`: its text, read whole so words split across elements count, and its text attributes. */
function unfilledUnder(node: Node): string[] {
  if (node instanceof Document) return unfilledUnder(node.documentElement)
  if (node.nodeType === Node.TEXT_NODE) return inContext(node.nodeValue ?? "")
  if (!(node instanceof Element)) return []
  const labels = [node, ...node.querySelectorAll("*")].flatMap((element) =>
    TEXT_ATTRIBUTES.flatMap((name) => inContext(element.getAttribute(name) ?? "")),
  )
  return [...inContext(node.textContent), ...labels]
}

function unfilledIn(record: MutationRecord): string[] {
  if (record.type === "childList") return [...record.addedNodes].flatMap(unfilledUnder)
  if (record.type === "characterData") return unfilledUnder(record.target)
  const name = record.attributeName ?? ""
  if (!TEXT_ATTRIBUTES.includes(name) || !(record.target instanceof Element)) return []
  return inContext(record.target.getAttribute(name) ?? "")
}

export type UnfilledWatch = {
  /** Stops watching, and returns each text with unfilled words shown since it began, once. */
  stop: () => string[]
}

/**
 * Watches `root` for unfilled words from now on, as each change shows them, so text a test shows
 * and then removes still counts; what `root` holds when it stops counts too.
 */
export function watchUnfilledText(root: Node): UnfilledWatch {
  const found = new Set<string>()
  const record = (records: MutationRecord[]) => {
    for (const text of records.flatMap(unfilledIn)) found.add(text)
  }
  const observer = new MutationObserver(record)
  observer.observe(root, { subtree: true, childList: true, characterData: true, attributes: true })
  return {
    stop: () => {
      record(observer.takeRecords())
      observer.disconnect()
      for (const text of unfilledUnder(root)) found.add(text)
      return [...found]
    },
  }
}
