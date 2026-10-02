type SummarizedAccount = { state: string }

export type AccountSummary = {
  /** One line for the collapsed list, such as "2 accounts connected, 1 needs reauthorization". */
  text: string
  needsAttention: boolean
}

export function accountSummary(accounts: readonly SummarizedAccount[]): AccountSummary {
  const disconnected = accounts.filter((account) => account.state !== "connected").length
  const connected = accounts.length - disconnected
  const reauthorize = `${disconnected} ${disconnected === 1 ? "needs" : "need"} reauthorization`
  if (disconnected === 0) {
    return { text: `${connected} account${connected === 1 ? "" : "s"} connected`, needsAttention: false }
  }
  if (connected === 0) {
    const text = `${disconnected} account${disconnected === 1 ? "" : "s"} disconnected`
    return { text: `${text}, ${disconnected === 1 ? "it needs" : "they need"} reauthorization`, needsAttention: true }
  }
  return {
    text: `${connected} account${connected === 1 ? "" : "s"} connected, ${reauthorize}`,
    needsAttention: true,
  }
}
