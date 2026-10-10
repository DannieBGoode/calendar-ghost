import type { I18n } from "@/i18n/translator"

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
