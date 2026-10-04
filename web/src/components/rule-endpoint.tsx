import { AccountAvatar } from "@/components/account-avatar"
import { useI18n } from "@/i18n/provider"
import type { MessageKey } from "@/i18n/types"
import type { ConnectedAccount, DiscoveredCalendar, RuleCalendar } from "@/lib/api"
import { ruleEndpointLabel } from "@/lib/rule-endpoint"

const ROLE_LABEL_KEYS: Record<"Source" | "Destination", MessageKey> = {
  Source: "rules.endpoint.role.source",
  Destination: "rules.endpoint.role.destination",
}

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
  const i18n = useI18n()
  const label = ruleEndpointLabel(i18n, endpoint, account, calendars)
  return (
    <span className="rule-endpoint" title={`${label.calendar} · ${account?.email ?? endpoint.connected_account_id}`}>
      <AccountAvatar
        displayName={account?.display_name ?? ""}
        email={account?.email ?? endpoint.connected_account_id}
        avatarUrl={account?.avatar_url}
        compact
      />
      <span className="rule-endpoint-copy">
        <span className="sr-only">{i18n.t(ROLE_LABEL_KEYS[role])}</span>
        <span className="rule-endpoint-calendar">{label.calendar}</span>
        <span className="rule-endpoint-account">{label.account}</span>
      </span>
    </span>
  )
}
