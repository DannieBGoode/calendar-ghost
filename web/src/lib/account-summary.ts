import type { I18n } from "@/i18n/translator"

type SummarizedAccount = { state: string; rule_count: number }

export type AccountSummary = {
  /** One line for the collapsed list, such as "2 accounts connected, 1 needs reauthorization". */
  text: string
  needsAttention: boolean
  /** Whether a disconnected account has stopped rules, which makes it urgent rather than a look. */
  stopsRules: boolean
}

export function accountSummary(i18n: I18n, accounts: readonly SummarizedAccount[]): AccountSummary {
  const disconnectedAccounts = accounts.filter((account) => account.state !== "connected")
  const disconnected = disconnectedAccounts.length
  const stopsRules = disconnectedAccounts.some((account) => account.rule_count > 0)
  const connected = accounts.length - disconnected
  if (disconnected === 0) {
    return {
      text: i18n.t("overview.accountSummary.connectedOnly", { count: connected }),
      needsAttention: false,
      stopsRules,
    }
  }
  if (connected === 0) {
    return {
      text: i18n.t("overview.accountSummary.disconnectedOnly", { count: disconnected }),
      needsAttention: true,
      stopsRules,
    }
  }
  const reauthorize = i18n.t("overview.accountSummary.reauthorizeCount", { count: disconnected })
  return {
    text: i18n.t("overview.accountSummary.mixed", { count: connected, reauthorize }),
    needsAttention: true,
    stopsRules,
  }
}
