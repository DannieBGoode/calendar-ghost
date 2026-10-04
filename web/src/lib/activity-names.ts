import type { I18n } from "@/i18n/translator"
import type { MessageKey } from "@/i18n/types"

/** How Activity copy names the calendars of an entry's rule. */

/** Calendar names of the entry's rule, or null once the rule is removed. */
export type RuleNames = { source: string; destination: string }

export function unnamed(i18n: I18n): RuleNames {
  return { source: i18n.t("activity.names.source"), destination: i18n.t("activity.names.destination") }
}

export function named(i18n: I18n, key: MessageKey, names: RuleNames | null): string {
  const { source, destination } = names ?? unnamed(i18n)
  return i18n.t(key, { source, destination })
}

export function capitalized(i18n: I18n, text: string): string {
  return `${text.charAt(0).toLocaleUpperCase(i18n.locale)}${text.slice(1)}`
}
