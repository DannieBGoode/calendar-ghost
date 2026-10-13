import { ArrowRight, SlidersHorizontal } from "lucide-react"
import { Fragment } from "react"

import { AccountAvatar } from "@/components/account-avatar"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import type { ConnectedAccount, RuleDetail } from "@/lib/api"
import { tentativeTitleShort } from "@/lib/invitation-responses"
import { appPathForRule, isPlainLeftClick } from "@/lib/navigation"
import { accountNoun } from "@/lib/providers"

/** An address that may break after its "@" on a narrow screen, never in the middle of a word. */
function Email({ address }: { address: string }) {
  const at = address.indexOf("@") + 1
  return (
    <span className="rule-preview-email">
      {at > 0 ? (
        <>
          {address.slice(0, at)}
          <wbr />
          {address.slice(at)}
        </>
      ) : (
        address
      )}
    </span>
  )
}

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
      {account ? (
        // Provider and address apart, so a narrow screen can put them on two lines and shorten
        // only the address.
        <span className="rule-endpoint-account rule-preview-account">
          <span>{accountNoun(i18n, account.provider)}</span>
          <Email address={account.email} />
        </span>
      ) : (
        <span className="rule-endpoint-account">{fallback}</span>
      )}
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

/** How the rule treats Maybe events and unanswered invitations, in a few words each. */
function invitationFacts(i18n: I18n, detail: RuleDetail): string[] {
  const { t } = i18n
  const maybe = {
    mark: t("rulePreview.rule.maybeAs", { title: tentativeTitleShort(detail.privacy_policy) }),
    sync: t("rulePreview.rule.maybeSync"),
    skip: t("rulePreview.rule.maybeOff"),
  }[detail.tentative_events]
  if (detail.unanswered_invitations === "wait") return [maybe, t("rulePreview.rule.unansweredWait")]
  return [maybe, detail.tentative_events === "skip" ? t("rulePreview.rule.unansweredOff") : t("rulePreview.rule.unansweredAs")]
}

/** The rule's choices in a few words each, in the order Rule Details lists them. */
function settingsFacts(i18n: I18n, detail: RuleDetail): string[] {
  const { t } = i18n
  return [
    t("rulePreview.rule.since", { count: detail.initial_lookback_days }),
    detail.sync_all_day_events ? t("rulePreview.rule.allDayOn") : t("rulePreview.rule.allDayOff"),
    detail.sync_birthdays ? t("rulePreview.rule.birthdaysOn") : t("rulePreview.rule.birthdaysOff"),
    ...invitationFacts(i18n, detail),
    t("rulePreview.rule.declinedOff"),
  ]
}

/**
 * The choices this preview follows, on one quiet line under the privacy line, with the way to change
 * them at its end.
 */
export function PreviewSettings({ detail, onChange }: { detail: RuleDetail; onChange: () => void }) {
  const i18n = useI18n()
  const { t } = i18n
  return (
    <p className="rule-preview-settings">
      <SlidersHorizontal aria-hidden="true" />
      <span>
        <span className="sr-only">{t("rulePreview.rule.settings")} </span>
        {settingsFacts(i18n, detail).map((fact, index) => (
          <Fragment key={fact}>
            {index > 0 && " · "}
            <span className="rule-preview-fact">{fact}</span>
          </Fragment>
        ))}
        <Button variant="ghost" size="sm" className="rule-preview-inline-action" asChild>
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
        </Button>
      </span>
    </p>
  )
}
