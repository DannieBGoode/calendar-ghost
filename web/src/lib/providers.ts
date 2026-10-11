import type { I18n } from "@/i18n/translator"
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

/** Where the browser goes to connect an account of the provider, or to reauthorize `accountId`. */
export function connectUrl(provider: CalendarProvider, accountId?: string): string {
  return accountId ? `${provider.connect_url}?account=${encodeURIComponent(accountId)}` : provider.connect_url
}
