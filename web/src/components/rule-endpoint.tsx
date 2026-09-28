import { AccountAvatar } from "@/components/account-avatar"
import type { ConnectedAccount, DiscoveredCalendar } from "@/lib/api"
import { ruleEndpointLabel } from "@/lib/rule-endpoint"

export function RuleEndpoint({
  account,
  accountId,
  calendarId,
  calendars,
  role,
}: {
  account: ConnectedAccount | undefined
  accountId: string
  calendarId: string
  calendars: DiscoveredCalendar[] | undefined
  role: "Source" | "Destination"
}) {
  const label = ruleEndpointLabel(calendarId, account, calendars)
  return (
    <span className="rule-endpoint" title={`${label.calendar} · ${account?.email ?? accountId}`}>
      <AccountAvatar
        displayName={account?.display_name ?? ""}
        email={account?.email ?? accountId}
        avatarUrl={account?.avatar_url}
        compact
      />
      <span className="rule-endpoint-copy">
        <span className="sr-only">{role}: </span>
        <span className="rule-endpoint-calendar">{label.calendar}</span>
        <span className="rule-endpoint-account">{label.account}</span>
      </span>
    </span>
  )
}
