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
  visit,
  onViewChange,
  onOpenRule,
}: {
  location: AppLocation
  arrival: ViewOptions
  visit: number
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
        notice={arrival.notice ? { text: arrival.notice, attention: arrival.noticeTone === "attention" } : null}
        createRule={arrival.createRule === true}
        onViewChange={onViewChange}
        onOpenRule={onOpenRule}
      />
    )
  }
  // Remounted on every arrival so its filters always match the address it was opened at.
  if (view === "activity") return <ActivityView key={visit} onViewChange={onViewChange} onOpenRule={onOpenRule} />
  if (view === "settings") return <SettingsPage onViewChange={onViewChange} />
  return <OverviewView onViewChange={onViewChange} onOpenRule={onOpenRule} />
}
