import { SearchField } from "@/components/search-field"
import { Label } from "@/components/ui/label"
import { NativeSelect } from "@/components/ui/native-select"
import { useI18n } from "@/i18n/provider"
import type { PeopleQuery, PlanSummary } from "@/lib/api"
import { VERDICTS } from "@/lib/operator-overview"
import { heldPlanName } from "@/lib/plans"

type Filters = Pick<PeopleQuery, "search" | "role" | "state" | "verdict" | "plan">

/**
 * Search by part of an email, and narrow to one role, state, sync status, or, once `plans` are
 * known, Plan.
 */
export function PeopleFilters({
  query,
  plans,
  onChange,
}: {
  query: Filters
  plans: readonly PlanSummary[] | undefined
  onChange: (next: Partial<Filters>) => void
}) {
  const { t } = useI18n()
  return (
    <div className="people-filters" data-plans={plans !== undefined}>
      <SearchField
        id="people-search"
        label={t("people.filters.search")}
        placeholder={t("people.filters.searchPlaceholder")}
        clearLabel={t("people.filters.clearSearch")}
        query={query.search}
        onSearch={(search) => onChange({ search })}
      />
      <div className="field-stack">
        <Label htmlFor="people-role">{t("people.filters.role")}</Label>
        <NativeSelect
          id="people-role"
          value={query.role}
          onChange={(event) => onChange({ role: event.target.value as Filters["role"] })}
        >
          <option value="">{t("people.filters.anyRole")}</option>
          <option value="installation_administrator">{t("people.filters.administrators")}</option>
          <option value="user">{t("people.filters.users")}</option>
        </NativeSelect>
      </div>
      <div className="field-stack">
        <Label htmlFor="people-state">{t("people.filters.state")}</Label>
        <NativeSelect
          id="people-state"
          value={query.state}
          onChange={(event) => onChange({ state: event.target.value as Filters["state"] })}
        >
          <option value="">{t("people.filters.anyState")}</option>
          <option value="active">{t("people.filters.active")}</option>
          <option value="disabled">{t("people.filters.disabled")}</option>
        </NativeSelect>
      </div>
      <div className="field-stack">
        <Label htmlFor="people-verdict">{t("people.filters.verdict")}</Label>
        <NativeSelect
          id="people-verdict"
          value={query.verdict}
          onChange={(event) => onChange({ verdict: event.target.value as Filters["verdict"] })}
        >
          <option value="">{t("people.filters.anyVerdict")}</option>
          {VERDICTS.map((verdict) => (
            <option key={verdict} value={verdict}>
              {t(`people.verdicts.${verdict}`)}
            </option>
          ))}
        </NativeSelect>
      </div>
      {plans && <PlanFilter plans={plans} plan={query.plan} onChange={(plan) => onChange({ plan })} />}
    </div>
  )
}

/**
 * Narrows to the people who have one Plan, their own or as the default, as the Plans tab counts
 * them, named as their Plan column names it. A Plan the address names that no longer exists stays
 * chosen, and says so, so the select never shows a filter other than the one in use.
 */
function PlanFilter({
  plans,
  plan,
  onChange,
}: {
  plans: readonly PlanSummary[]
  plan: string
  onChange: (plan: string) => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  const missing = plan !== "" && !plans.some((listed) => listed.key === plan)
  return (
    <div className="field-stack">
      <Label htmlFor="people-plan">{t("people.filters.plan")}</Label>
      <NativeSelect id="people-plan" value={plan} onChange={(event) => onChange(event.target.value)}>
        <option value="">{t("people.filters.anyPlan")}</option>
        {plans.map(({ key, name, is_default }) => (
          <option key={key} value={key}>
            {heldPlanName(i18n, { name, on_default: is_default })}
          </option>
        ))}
        {missing && <option value={plan}>{t("people.filters.missingPlan")}</option>}
      </NativeSelect>
    </div>
  )
}
