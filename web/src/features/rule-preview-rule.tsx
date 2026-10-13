import { ArrowRight, ChevronDown, ListFilter, Settings2 } from "lucide-react"

import { AccountAvatar } from "@/components/account-avatar"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/i18n/provider"
import type { ConnectedAccount, RuleDetail } from "@/lib/api"
import { tentativeFact, unansweredFact } from "@/lib/invitation-responses"
import { appPathForRule, isPlainLeftClick } from "@/lib/navigation"
import { accountNoun } from "@/lib/providers"

/** One account the rule reads or writes, naming its provider in words beside the avatar's mark. */
function PreviewAccount({ account, fallback }: { account: ConnectedAccount | undefined; fallback: string }) {
  const i18n = useI18n()
  return (
    <span className="rule-endpoint">
      <AccountAvatar
        displayName={account?.display_name ?? ""}
        email={account?.email ?? fallback}
        avatarUrl={account?.avatar_url}
        provider={account?.provider}
        compact
      />
      <span className="rule-endpoint-account">
        {account
          ? i18n.t("rulePreview.rule.account", { provider: accountNoun(i18n, account.provider), email: account.email })
          : fallback}
      </span>
    </span>
  )
}

/**
 * The accounts and providers under the title, in its order; the title already names the calendars.
 * A rule within one account shows it once.
 */
export function PreviewAccounts({ detail, accounts }: { detail: RuleDetail; accounts: ConnectedAccount[] }) {
  const sourceId = detail.source.connected_account_id
  const destinationId = detail.destination.connected_account_id
  const accountOf = (id: string) => accounts.find((account) => account.id === id)
  return (
    <p className="rule-direction rule-preview-accounts">
      <PreviewAccount account={accountOf(sourceId)} fallback={sourceId} />
      {destinationId !== sourceId && (
        <>
          <ArrowRight aria-hidden="true" />
          <PreviewAccount account={accountOf(destinationId)} fallback={destinationId} />
        </>
      )}
    </p>
  )
}

/** The choices this preview follows, in the words Rule Details uses, folded to one line until asked. */
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
    <div className="rule-preview-settings">
      <details className="inline-help">
        <summary>
          <ListFilter aria-hidden="true" />
          <span>{t("rulePreview.rule.settings")}</span>
          <ChevronDown className="inline-help-chevron" aria-hidden="true" />
        </summary>
        <dl>
          {settings.map(([term, value]) => (
            <div key={term}>
              <dt>{term}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      </details>
      <Button variant="ghost" size="icon" className="rule-preview-change" asChild>
        <a
          href={appPathForRule(detail.id)}
          aria-label={t("rulePreview.rule.change")}
          title={t("rulePreview.rule.change")}
          onClick={(event) => {
            if (!isPlainLeftClick(event)) return
            event.preventDefault()
            onChange()
          }}
        >
          <Settings2 aria-hidden="true" />
        </a>
      </Button>
    </div>
  )
}
