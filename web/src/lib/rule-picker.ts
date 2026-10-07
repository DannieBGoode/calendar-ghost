/** Keyboard behaviour of the select-only combobox pattern (WAI-ARIA APG) used by the rule picker. */

/** Which option a key opens the closed list on, or null when the key does not open it. */
export function openingIndex(key: string, altKey: boolean, selected: number, count: number): number | null {
  if (count === 0) return null
  if (key === "Home") return 0
  if (key === "End") return count - 1
  if (["ArrowDown", "ArrowUp", "Enter", " "].includes(key) || (altKey && key === "ArrowDown")) {
    return Math.max(selected, 0)
  }
  return null
}

/** A printable character other than Space, typed without a shortcut modifier, searches the options. */
export function isTypeaheadKey(event: { key: string; ctrlKey: boolean; metaKey: boolean }): boolean {
  return event.key.length === 1 && event.key !== " " && !event.ctrlKey && !event.metaKey
}

/** What a key does to the open list other than moving within it. */
export type ListCommand = "close" | "choose" | "chooseAndLeave"

/**
 * Escape closes the open list; Enter, Space, and Alt+ArrowUp choose the active option; Tab chooses
 * it as focus moves on. Null for every other key.
 */
export function listCommand(key: string, altKey: boolean): ListCommand | null {
  if (key === "Escape") return "close"
  if (key === "Enter" || key === " " || (altKey && key === "ArrowUp")) return "choose"
  if (key === "Tab") return "chooseAndLeave"
  return null
}

/** The option a navigation key moves to in the open list, or null for other keys. */
export function movedIndex(key: string, active: number, count: number): number | null {
  const page = 10
  switch (key) {
    case "ArrowDown":
      return Math.min(active + 1, count - 1)
    case "ArrowUp":
      return Math.max(active - 1, 0)
    case "Home":
      return 0
    case "End":
      return count - 1
    case "PageDown":
      return Math.min(active + page, count - 1)
    case "PageUp":
      return Math.max(active - page, 0)
    default:
      return null
  }
}

/**
 * Typeahead: the next option after `from` whose label starts with the typed text. Repeating one
 * letter cycles through the options that start with it. `locale` keeps the case-folding rules of
 * the active language rather than the runtime's default locale.
 */
export function typeaheadIndex(labels: readonly string[], typed: string, from: number, locale: string): number {
  const query = typed.toLocaleLowerCase(locale)
  if (!query) return -1
  const cycling = query.replaceAll(query.charAt(0), "") === ""
  const needle = cycling ? query.charAt(0) : query
  const start = cycling || query.length === 1 ? from + 1 : from
  for (let offset = 0; offset < labels.length; offset += 1) {
    const index = (start + offset) % labels.length
    if (labels[index]?.toLocaleLowerCase(locale).startsWith(needle)) return index
  }
  return -1
}
