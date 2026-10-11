import type { I18n } from "@/i18n/translator"
import type { MessageKey } from "@/i18n/types"
import type { CalendarProvider } from "@/lib/api"

/** The connectable provider of this kind, as an account, problem, or hint names it. */
export function providerOf(
  providers: readonly CalendarProvider[],
  kind: string | null | undefined,
): CalendarProvider | null {
  return providers.find((provider) => provider.kind === kind) ?? null
}

/** How the interface names a provider, such as "Google"; its own name when the catalog has none. */
export function providerDisplayName(i18n: I18n, kind: string | null | undefined, providers: readonly CalendarProvider[] = []): string {
  const key = `common.providerName.${String(kind)}`
  if (kind && i18n.has(key)) return i18n.t(key)
  return providerOf(providers, kind)?.display_name ?? i18n.t("common.providerName.unknown")
}

/** How the interface names an account of a provider, such as "Google account" (CONTEXT.md). */
export function accountNoun(i18n: I18n, kind: string | null | undefined, providers: readonly CalendarProvider[] = []): string {
  const key = `common.providerAccount.${String(kind)}`
  if (kind && i18n.has(key)) return i18n.t(key)
  const provider = providerOf(providers, kind)
  return provider
    ? i18n.t("common.providerAccount.named", { name: provider.display_name })
    : i18n.t("common.providerAccount.unknown")
}

/** A catalog's word for the provider at `key`, or the neutral `fallback` when the catalog has none. */
function catalogWord(i18n: I18n, key: string | null, fallback: MessageKey): string {
  return key && i18n.has(key) ? i18n.t(key) : i18n.t(fallback)
}

/** Every way a message names one provider: "Google", "Google Calendar", "Google account", and where it is fixed. */
export type ProviderWords = {
  provider: string
  Provider: string
  calendar: string
  Calendar: string
  account: string
  api: string
  console: string
  status: string
}

/** How messages name the provider of this kind; neutral words when no one provider is meant. */
export function providerWords(i18n: I18n, kind: string | null | undefined): ProviderWords {
  const name = kind ? `common.providerName.${kind}` : null
  const calendar = kind ? `common.provider.${kind}` : null
  return {
    provider: catalogWord(i18n, name, "common.providerName.unknown"),
    Provider: catalogWord(i18n, name, "common.providerName.unknownStart"),
    calendar: catalogWord(i18n, calendar, "common.provider.unknown"),
    Calendar: catalogWord(i18n, calendar, "common.provider.unknownStart"),
    account: accountNoun(i18n, kind),
    api: catalogWord(i18n, kind ? `common.providerApi.${kind}` : null, "common.providerApi.unknown"),
    console: catalogWord(i18n, kind ? `common.providerConsole.${kind}` : null, "common.providerConsole.unknown"),
    status: catalogWord(i18n, kind ? `common.providerStatus.${kind}` : null, "common.providerStatus.unknown"),
  }
}

/** Where the browser goes to connect an account of the provider, or to reauthorize `accountId`. */
export function connectUrl(provider: CalendarProvider, accountId?: string): string {
  return accountId ? `${provider.connect_url}?account=${encodeURIComponent(accountId)}` : provider.connect_url
}
