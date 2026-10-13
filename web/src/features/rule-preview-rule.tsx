import { ArrowRight } from "lucide-react"

import { AccountAvatar } from "@/components/account-avatar"
import { useI18n } from "@/i18n/provider"
import type { ConnectedAccount, RuleDetail } from "@/lib/api"
import { tentativeFact, unansweredFact } from "@/lib/invitation-responses"
import { appPathForRule, isPlainLeftClick } from "@/lib/navigation"
import { accountNoun } from "@/lib/providers"
import { ruleEndpointLabel } from "@/lib/rule-endpoint"
import type { CalendarsByAccount } from "@/lib/use-rule-calendars"

/** One calendar with its account, naming the provider in words beside the avatar's mark. */
function PreviewCalendar({
  endpoint,
  account,
  calendars,
  roleLabel,
}: {
  endpoint: RuleDetail["source"]
  account: ConnectedAccount | undefined
  calendars: CalendarsByAccount
  roleLabel: string
}) {
  const i18n = useI18n()
  const label = ruleEndpointLabel(i18n, endpoint, account, calendars.get(endpoint.connected_account_id))
  const owner = account
    ? i18n.t("rulePreview.rule.account", { provider: accountNoun(i18n, account.provider), email: account.email })
    : label.account
  return (
    <span className="rule-endpoint">
      <AccountAvatar
        displayName={account?.display_name ?? ""}
        email={account?.email ?? endpoint.connected_account_id}
        avatarUrl={account?.avatar_url}
        provider={account?.provider}
        compact
      />
      <span className="rule-endpoint-copy">
        <span className="rule-endpoint-calendar">
          {label.calendar} <span className="rule-preview-role">{roleLabel}</span>
        </span>
        <span className="rule-endpoint-account">{owner}</span>
      </span>
    </span>
  )
}

/** Which calendars the rule connects, on which accounts and providers. */
export function PreviewCalendars({
  detail,
  accounts,
  calendars,
}: {
  detail: RuleDetail
  accounts: ConnectedAccount[]
  calendars: CalendarsByAccount
}) {
  const { t } = useI18n()
  const accountOf = (endpoint: RuleDetail["source"]) =>
    accounts.find((account) => account.id === endpoint.connected_account_id)
  return (
    <p className="rule-direction rule-preview-calendars">
      <PreviewCalendar
        endpoint={detail.source}
        account={accountOf(detail.source)}
        calendars={calendars}
        roleLabel={t("rulePreview.table.source")}
      />
      <ArrowRight aria-hidden="true" />
      <PreviewCalendar
        endpoint={detail.destination}
        account={accountOf(detail.destination)}
        calendars={calendars}
        roleLabel={t("rulePreview.table.destination")}
      />
    </p>
  )
}

/** The choices this preview follows, in the words Rule Details uses, with a way to change them. */
export function PreviewSettings({ detail, onChange }: { detail: RuleDetail; onChange: () => void }) {
  const i18n = useI18n()
  const { t } = i18n
  const settings: [string, string][] = [
    [t("ruleDetails.facts.allDay"), detail.sync_all_day_events ? t("ruleDetails.facts.allDayIncluded") : t("ruleDetails.facts.allDayExcluded")],
    [t("ruleDetails.facts.birthdays"), detail.sync_birthdays ? t("ruleDetails.facts.birthdaysIncluded") : t("ruleDetails.facts.birthdaysExcluded")],
    [t("ruleDetails.facts.tentative"), tentativeFact(i18n, detail)],
    [t("ruleDetails.facts.unanswered"), unansweredFact(i18n, detail)],
    [t("ruleDetails.facts.declined"), t("ruleDetails.facts.declinedValue")],
    [t("ruleDetails.facts.startingPoint"), t("ruleDetails.facts.startingPointValue", { count: detail.initial_lookback_days })],
  ]
  return (
    <section className="rule-preview-settings" aria-labelledby="rule-preview-settings-title">
      <div className="rule-preview-settings-heading">
        <h2 id="rule-preview-settings-title">{t("rulePreview.rule.settings")}</h2>
        <a
          href={appPathForRule(detail.id)}
          onClick={(event) => {
            if (!isPlainLeftClick(event)) return
            event.preventDefault()
            onChange()
          }}
        >
          {t("rulePreview.rule.change")}
        </a>
      </div>
      <dl>
        {settings.map(([term, value]) => (
          <div key={term}>
            <dt>{term}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}
