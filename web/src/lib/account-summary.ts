type SummarizedAccount = { state: string; rule_count: number }

export type AccountSummary = {
  /** One line for the collapsed list, such as "2 accounts connected, 1 needs reauthorization". */
  text: string
  needsAttention: boolean
  /** Whether a disconnected account has stopped rules, which makes it urgent rather than a look. */
  stopsRules: boolean
}

export function accountSummary(accounts: readonly SummarizedAccount[]): AccountSummary {
  const disconnectedAccounts = accounts.filter((account) => account.state !== "connected")
  const disconnected = disconnectedAccounts.length
  const stopsRules = disconnectedAccounts.some((account) => account.rule_count > 0)
  const connected = accounts.length - disconnected
  const reauthorize = `${disconnected} ${disconnected === 1 ? "needs" : "need"} reauthorization`
  if (disconnected === 0) {
    return { text: `${connected} account${connected === 1 ? "" : "s"} connected`, needsAttention: false, stopsRules }
  }
  if (connected === 0) {
    const text = `${disconnected} account${disconnected === 1 ? "" : "s"} disconnected`
    return {
      text: `${text}, ${disconnected === 1 ? "it needs" : "they need"} reauthorization`,
      needsAttention: true,
      stopsRules,
    }
  }
  return {
    text: `${connected} account${connected === 1 ? "" : "s"} connected, ${reauthorize}`,
    needsAttention: true,
    stopsRules,
  }
}
