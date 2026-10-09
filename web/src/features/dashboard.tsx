import { ActivityView } from "@/features/activity"
import { OverviewView } from "@/features/overview"
import { PeopleView } from "@/features/people-page"
import { PersonView } from "@/features/person-page"
import { RuleDetailsView } from "@/features/rule-details"
import { RulesView } from "@/features/rules"
import { SettingsPage } from "@/features/settings"
import {
  activitySearch,
  DEFAULT_PEOPLE_TAB,
  DEFAULT_SETTINGS_TAB,
  type AppLocation,
  type OpenPerson,
  type OpenRule,
  type OpenSettingsTab,
  type ViewChange,
  type ViewOptions,
} from "@/lib/navigation"

/** Routes to one view; each view loads only the data it needs so none waits on another's. */
export function Dashboard({
  location,
  arrival,
  visit,
  onViewChange,
  onOpenRule,
  onOpenSettingsTab,
  onOpenPerson,
}: {
  location: AppLocation
  arrival: ViewOptions
  visit: number
  onViewChange: ViewChange
  onOpenRule: OpenRule
  onOpenSettingsTab: OpenSettingsTab
  onOpenPerson: OpenPerson
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
  if (view === "people") {
    return (
      <PeopleRoute
        location={location}
        arrival={arrival}
        visit={visit}
        onViewChange={onViewChange}
        onOpenPerson={onOpenPerson}
      />
    )
  }
  if (view === "settings") {
    return (
      <SettingsPage
        ownActions={{
          openRule: onOpenRule,
          openConnections: () => onOpenSettingsTab("connections"),
          openActivity: (ruleId) => onViewChange("activity", ruleId ? { search: activitySearch(ruleId) } : {}),
        }}
        tab={location.settingsTab ?? DEFAULT_SETTINGS_TAB}
        onOpenTab={onOpenSettingsTab}
        onOpenPeople={() => onViewChange("people")}
      />
    )
  }
  return <OverviewView onViewChange={onViewChange} onOpenRule={onOpenRule} />
}

/** People, or one person's page under it. */
function PeopleRoute({
  location: { personId, peopleTab },
  arrival: { notice },
  visit,
  onViewChange,
  onOpenPerson,
}: {
  location: AppLocation
  arrival: ViewOptions
  visit: number
  onViewChange: ViewChange
  onOpenPerson: OpenPerson
}) {
  if (personId) {
    return (
      <PersonView
        key={personId}
        personId={personId}
        onBack={() => onViewChange("people")}
        onDeleted={(deleted) => onViewChange("people", { notice: deleted })}
      />
    )
  }
  // Remounted on every arrival so its search, filters, and page match the address.
  return <PeopleView key={visit} tab={peopleTab ?? DEFAULT_PEOPLE_TAB} notice={notice ?? null} onOpenPerson={onOpenPerson} />
}
