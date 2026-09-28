import { accountInitials } from "@/lib/account-avatar"
import type { ConnectedAccount } from "@/lib/api"

export function RuleEndpoint({
  account,
  accountId,
  calendarId,
}: {
  account: ConnectedAccount | undefined
  accountId: string
  calendarId: string
}) {
  return (
    <span className="rule-endpoint" title={account?.email ?? accountId}>
      <span className="account-mark account-mark-compact" aria-hidden="true">
        {accountInitials(account?.display_name ?? "", account?.email ?? accountId)}
      </span>
      <span>{calendarId}</span>
    </span>
  )
}
