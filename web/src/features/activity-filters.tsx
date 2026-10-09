import { RulePicker, type RulePickerOption } from "@/components/rule-picker"
import { SearchField } from "@/components/search-field"
import { Label } from "@/components/ui/label"
import { NativeSelect } from "@/components/ui/native-select"
import { useI18n } from "@/i18n/provider"
import { SHOW_FILTERS } from "@/lib/activity"
import type { ActivityLocationState, ActivityShow } from "@/lib/activity-location"
import { endpointName, type RuleContext } from "@/lib/activity-rule-context"
import type { AuditEntry, RuleSummary } from "@/lib/api"

export function ActivityFilters({
  query,
  ruleId,
  show,
  entries,
  context,
  onChange,
}: {
  query: string
  ruleId: string
  show: ActivityShow
  entries: AuditEntry[]
  context: RuleContext
  onChange: (next: Partial<ActivityLocationState>) => void
}) {
  const { t } = useI18n()
  const pickerOptions = rulePickerOptions(ruleId, entries, context)
  return (
    <div className="activity-filters">
      <SearchField
        id="activity-search"
        label={t("activity.search.label")}
        placeholder={t("activity.search.placeholder")}
        clearLabel={t("activity.search.clear")}
        query={query}
        onSearch={(next) => onChange({ query: next })}
      />
      <div className="field-stack">
        <Label id="activity-rule-label" onClick={() => document.getElementById("activity-rule")?.focus()}>{t("activity.filters.rule")}</Label>
        <RulePicker
          id="activity-rule"
          labelId="activity-rule-label"
          value={ruleId}
          options={pickerOptions.options}
          showAccounts={pickerOptions.showAccounts}
          clearValue=""
          clearLabel={t("activity.filters.showAllRules")}
          onChange={(value) => onChange({ ruleId: value })}
        />
      </div>
      <div className="field-stack">
        <Label htmlFor="activity-category">{t("activity.filters.show")}</Label>
        <NativeSelect id="activity-category" value={show} onChange={(event) => onChange({ show: event.target.value as ActivityShow })}>
          {SHOW_FILTERS.map((filter) => <option key={filter.value} value={filter.value}>{t(filter.label)}</option>)}
        </NativeSelect>
      </div>
    </div>
  )
}

function rulePickerOptions(
  ruleId: string,
  entries: AuditEntry[],
  context: RuleContext,
): { options: RulePickerOption[]; showAccounts: boolean } {
  const { t } = context.i18n
  const rules = [...context.rulesById.values()]
  const endpoint = (value: RuleSummary["source"]) => ({
    calendar: endpointName(value, context),
    accountId: value.connected_account_id,
    account: context.accountsById.get(value.connected_account_id),
  })
  // History can name rules that were removed; they stay filterable.
  const removed = context.rulesLoaded
    ? [...new Set([...entries.map((item) => item.rule_id), ...(ruleId ? [ruleId] : [])])].filter(
        (id) => !context.rulesById.has(id),
      )
    : []
  const options: RulePickerOption[] = [
    { value: "", name: t("activity.filters.allRules") },
    ...rules.map((rule) => {
      const source = endpoint(rule.source)
      const destination = endpoint(rule.destination)
      return {
        value: rule.id,
        name: t("activity.ruleName", { source: source.calendar, destination: destination.calendar }),
        source,
        destination,
      }
    }),
    ...removed.map((id, index) => ({
      value: id,
      name: removed.length > 1 ? t("activity.removedRuleNumbered", { number: index + 1 }) : t("activity.removedRule"),
      removed: true,
    })),
  ]
  // Calendar names alone cannot tell apart two calendars that share a name.
  const calendars = new Map<string, Set<string>>()
  for (const rule of rules) {
    for (const side of [rule.source, rule.destination]) {
      const name = endpointName(side, context)
      calendars.set(name, (calendars.get(name) ?? new Set()).add(`${side.connected_account_id}/${side.calendar_id}`))
    }
  }
  return { options, showAccounts: [...calendars.values()].some((ids) => ids.size > 1) }
}
