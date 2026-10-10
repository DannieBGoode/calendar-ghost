import { SearchField } from "@/components/search-field"
import { Label } from "@/components/ui/label"
import { NativeSelect } from "@/components/ui/native-select"
import { useI18n } from "@/i18n/provider"
import type { PeopleQuery } from "@/lib/api"
import { VERDICTS } from "@/lib/operator-overview"

type Filters = Pick<PeopleQuery, "search" | "role" | "state" | "verdict">

/** Search by part of an email, and narrow to one role, state, or sync status. */
export function PeopleFilters({ query, onChange }: { query: Filters; onChange: (next: Partial<Filters>) => void }) {
  const { t } = useI18n()
  return (
    <div className="people-filters">
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
    </div>
  )
}
