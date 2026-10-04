/** How Activity copy names the calendars of an entry's rule. */

/** Calendar names of the entry's rule, or null once the rule is removed. */
export type RuleNames = { source: string; destination: string }

export const UNNAMED: RuleNames = { source: "the source calendar", destination: "the destination calendar" }

export function named(text: string, names: RuleNames | null): string {
  const { source, destination } = names ?? UNNAMED
  return text.replaceAll("{source}", source).replaceAll("{destination}", destination)
}

export function capitalized(text: string): string {
  return `${text.charAt(0).toUpperCase()}${text.slice(1)}`
}
