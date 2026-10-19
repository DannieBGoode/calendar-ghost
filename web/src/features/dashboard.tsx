import { ActivityView } from "@/features/activity"
import { OverviewView } from "@/features/overview"
import { PeopleView } from "@/features/people-page"
import { PersonView } from "@/features/person-page"
import { RuleDetailsView } from "@/features/rule-details"
import { RulePreviewView } from "@/features/rule-preview"
import { RulesView } from "@/features/rules"
import { SettingsPage } from "@/features/settings"
import { peopleReturnSearch } from "@/lib/use-people"
import {
  DEFAULT_PEOPLE_TAB,
  DEFAULT_SETTINGS_TAB,
  type AppLocation,
  type OpenPerson,
  type OpenPlan,
  type OpenRule,
  type OpenRulePreview,
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
  onOpenRulePreview,
  onOpenSettingsTab,
  onOpenPerson,
  onOpenPlan,
}: {
  location: AppLocation
  arrival: ViewOptions
  visit: number
  onViewChange: ViewChange
  onOpenRule: OpenRule
  onOpenRulePreview: OpenRulePreview
  onOpenSettingsTab: OpenSettingsTab
  onOpenPerson: OpenPerson
  onOpenPlan: OpenPlan
}) {
  const view = location.view
  if (view === "rules") {
    return (
      <RulesRoute
        location={location}
        arrival={arrival}
        onViewChange={onViewChange}
        onOpenRule={onOpenRule}
        onOpenRulePreview={onOpenRulePreview}
      />
    )
  }
  // Remounted on every arrival so its filters always match the address it was opened at.
  if (view === "activity") {
    return (
      <ActivityView
        key={visit}
        tab={location.activityTab}
        incidentId={location.incidentId}
        onViewChange={onViewChange}
        onOpenRule={onOpenRule}
      />
    )
  }
  if (view === "people") {
    return (
      <PeopleRoute
        location={location}
        arrival={arrival}
        visit={visit}
        onViewChange={onViewChange}
        onOpenPerson={onOpenPerson}
        onOpenPlan={onOpenPlan}
        onOpenRule={onOpenRule}
        onOpenSettingsTab={onOpenSettingsTab}
      />
    )
  }
  if (view === "settings") {
    return (
      <SettingsPage
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
  arrival: { notice, planPanelFocus },
  visit,
  onViewChange,
  onOpenPerson,
  onOpenPlan,
  onOpenRule,
  onOpenSettingsTab,
}: {
  location: AppLocation
  arrival: ViewOptions
  visit: number
  onViewChange: ViewChange
  onOpenPerson: OpenPerson
  onOpenPlan: OpenPlan
  onOpenRule: OpenRule
  onOpenSettingsTab: OpenSettingsTab
}) {
  if (personId) {
    return (
      <PersonView
        key={personId}
        personId={personId}
        onBack={() => onViewChange("people", { search: peopleReturnSearch(personId) })}
        onDeleted={(deleted) => onViewChange("people", { notice: deleted, search: peopleReturnSearch(personId) })}
        own={{ openRule: onOpenRule, openConnections: () => onOpenSettingsTab("connections") }}
      />
    )
  }
  // Remounted on every arrival so its search, filters, and page match the address.
  return (
    <PeopleView
      key={visit}
      tab={peopleTab ?? DEFAULT_PEOPLE_TAB}
      notice={notice ?? null}
      onOpenPerson={onOpenPerson}
      onOpenPlan={onOpenPlan}
      panelFocus={planPanelFocus === true}
    />
  )
}

/** Rules, one rule's details, or its preview page. */
function RulesRoute({
  location: { ruleId, rulePreview },
  arrival,
  onViewChange,
  onOpenRule,
  onOpenRulePreview,
}: {
  location: AppLocation
  arrival: ViewOptions
  onViewChange: ViewChange
  onOpenRule: OpenRule
  onOpenRulePreview: OpenRulePreview
}) {
  if (ruleId !== null && rulePreview) {
    return <RulePreviewView key={ruleId} ruleId={ruleId} onViewChange={onViewChange} onOpenRule={onOpenRule} />
  }
  if (ruleId !== null) {
    return (
      <RuleDetailsView
        ruleId={ruleId}
        notice={arrival.notice ?? null}
        onViewChange={onViewChange}
        onOpenRule={onOpenRule}
        onOpenRulePreview={onOpenRulePreview}
      />
    )
  }
  return (
    <RulesView
      notice={arrival.notice ? { text: arrival.notice, attention: arrival.noticeTone === "attention" } : null}
      createRule={arrival.createRule === true}
      onViewChange={onViewChange}
      onOpenRule={onOpenRule}
      onOpenRulePreview={onOpenRulePreview}
    />
  )
}
