import { ActivityView } from "@/features/activity"
import { OverviewView } from "@/features/overview"
import { RuleDetailsView } from "@/features/rule-details"
import { RulesView } from "@/features/rules"
import { SettingsPage } from "@/features/settings"
import type { AppLocation, OpenRule, ViewChange, ViewOptions } from "@/lib/navigation"

/** Routes to one view; each view loads only the data it needs so none waits on another's. */
export function Dashboard({
  location,
  arrival,
  onViewChange,
  onOpenRule,
}: {
  location: AppLocation
  arrival: ViewOptions
  onViewChange: ViewChange
  onOpenRule: OpenRule
}) {
  const view = location.view
  if (view === "rules" && location.ruleId !== null) {
    return (
      <RuleDetailsView
        ruleId={location.ruleId}
        notice={arrival.notice ?? null}
        onViewChange={onViewChange}
        onOpenRule={onOpenRule}
      />
    )
  }
  if (view === "rules") {
    return (
      <RulesView
        notice={arrival.notice ?? null}
        createRule={arrival.createRule === true}
        onViewChange={onViewChange}
        onOpenRule={onOpenRule}
      />
    )
  }
  // Keyed by its filters so a link to one rule's activity applies even from the Activity view.
  if (view === "activity") return <ActivityView key={arrival.search ?? ""} />
  if (view === "settings") return <SettingsPage />
  return <OverviewView onViewChange={onViewChange} onOpenRule={onOpenRule} />
}
