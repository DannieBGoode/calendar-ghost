import { ArrowRight } from "lucide-react"

import { HappenedLine } from "@/components/activity-event"
import { RuleEndpoint } from "@/components/rule-endpoint"
import { whatHappened, type RuleNames } from "@/lib/activity"
import type { RuleContext } from "@/lib/activity-rule-context"
import type { AuditEntry } from "@/lib/api"

/** Labels the Activity table, its entry details, and its incidents share. */
export function HappenedLabel({ entry, names }: { entry: AuditEntry; names: RuleNames | null }) {
  return <HappenedLine happened={whatHappened(entry, names)} />
}

export function RuleDirection({ ruleId, context }: { ruleId: string; context: RuleContext }) {
  const rule = context.rulesById.get(ruleId)
  if (!rule) return <span className="activity-removed-rule">Removed rule</span>
  return (
    <span className="rule-direction activity-direction">
      <RuleEndpoint
        account={context.accountsById.get(rule.source.connected_account_id)}
        endpoint={rule.source}
        calendars={context.calendarsByAccount.get(rule.source.connected_account_id)}
        role="Source"
      />
      <ArrowRight aria-label="to" role="img" />
      <RuleEndpoint
        account={context.accountsById.get(rule.destination.connected_account_id)}
        endpoint={rule.destination}
        calendars={context.calendarsByAccount.get(rule.destination.connected_account_id)}
        role="Destination"
      />
    </span>
  )
}
