import { AccountAvatar } from "@/components/account-avatar"
import type { ConnectedAccount, DiscoveredCalendar, RuleCalendar } from "@/lib/api"
import { ruleEndpointLabel } from "@/lib/rule-endpoint"

export function RuleEndpoint({
  account,
  endpoint,
  calendars,
  role,
}: {
  account: ConnectedAccount | undefined
  endpoint: RuleCalendar
  calendars: DiscoveredCalendar[] | undefined
  role: "Source" | "Destination"
}) {
  const label = ruleEndpointLabel(endpoint, account, calendars)
  return (
    <span className="rule-endpoint" title={`${label.calendar} · ${account?.email ?? endpoint.connected_account_id}`}>
      <AccountAvatar
        displayName={account?.display_name ?? ""}
        email={account?.email ?? endpoint.connected_account_id}
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
