import type { I18n } from "@/i18n/translator"
import type { CalendarProvider } from "@/lib/api"
import { providerDisplayName } from "@/lib/providers"

type SummarizedAccount = { state: string; rule_count: number; authorization_lapsed_at?: string | null }

/**
 * Whether the account's rules wait on Reauthorization: it was disconnected, or Google stopped
 * accepting it while it stayed connected (Lapsed Authorization).
 */
export function needsReauthorization(account: SummarizedAccount): boolean {
  return account.state !== "connected" || Boolean(account.authorization_lapsed_at)
}

export type AccountSummary = {
  /** One line for the collapsed list, such as "3 accounts, 1 needs reauthorization". */
  text: string
  needsAttention: boolean
  /** Whether an account to reauthorize has stopped rules, which makes it urgent rather than a look. */
  stopsRules: boolean
}

export function accountSummary(i18n: I18n, accounts: readonly SummarizedAccount[]): AccountSummary {
  const unauthorizedAccounts = accounts.filter(needsReauthorization)
  const unauthorized = unauthorizedAccounts.length
  const stopsRules = unauthorizedAccounts.some((account) => account.rule_count > 0)
  const connected = accounts.length - unauthorized
  if (unauthorized === 0) {
    return {
      text: i18n.t("overview.accountSummary.connectedOnly", { count: connected }),
      needsAttention: false,
      stopsRules,
    }
  }
  if (connected === 0) {
    return {
      text: i18n.t("overview.accountSummary.reauthorizeOnly", { count: unauthorized }),
      needsAttention: true,
      stopsRules,
    }
  }
  const reauthorize = i18n.t("overview.accountSummary.reauthorizeCount", { count: unauthorized })
  // Every account counts, so a connected account that lapsed is not left out of the total.
  return {
    text: i18n.t("overview.accountSummary.mixed", { count: accounts.length, reauthorize }),
    needsAttention: true,
    stopsRules,
  }
}

/** The accounts' addresses grouped by provider, such as "Google: a@x, b@x · Microsoft: c@y". */
export function addressesByProvider(
  i18n: I18n,
  accounts: readonly { email: string; provider: string }[],
  providers: readonly CalendarProvider[] = [],
): string {
  const groups = new Map<string, string[]>()
  for (const account of accounts) groups.set(account.provider, [...(groups.get(account.provider) ?? []), account.email])
  return [...groups]
    .map(([kind, emails]) =>
      i18n.t("settings.accounts.addressesOf", {
        provider: providerDisplayName(i18n, kind, providers),
        addresses: i18n.format.unitList(emails),
      }),
    )
    .reduce((first, next) => i18n.t("settings.accounts.addressGroups", { first, next }))
}
