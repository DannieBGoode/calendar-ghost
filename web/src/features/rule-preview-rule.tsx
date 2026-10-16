import { ArrowRight, type LucideIcon } from "lucide-react"

import { AccountAvatar } from "@/components/account-avatar"
import { RULE_SETTING_ICONS } from "@/components/rule-setting-icons"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import type { ConnectedAccount, RuleDetail } from "@/lib/api"
import { tentativeMark } from "@/lib/invitation-responses"
import { appPathForRule, isPlainLeftClick } from "@/lib/navigation"
import { accountNoun } from "@/lib/providers"

/** An address that may break after its "@" on a narrow screen, never in the middle of a word. */
function Email({ address }: { address: string }) {
  const at = address.indexOf("@") + 1
  return (
    <span className="rule-preview-email" title={address}>
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

/**
 * One choice the preview follows, with an icon for what it is about. `off` marks a choice that
 * leaves events out, so it reads quieter than one that brings them in.
 */
type SettingFact = { text: string; icon: LucideIcon; off: boolean }

/** How the rule treats Maybe events and unanswered invitations, in a few words each. */
function invitationFacts(i18n: I18n, detail: RuleDetail): SettingFact[] {
  const { t } = i18n
  const mark = tentativeMark(detail.privacy_policy)
  const skipMaybe = detail.tentative_events === "skip"
  const maybe: SettingFact = {
    text: {
      mark: "title" in mark ? t("rulePreview.rule.maybeAs", mark) : t("rulePreview.rule.maybePrefixed", mark),
      sync: t("rulePreview.rule.maybeSync"),
      skip: t("rulePreview.rule.maybeOff"),
    }[detail.tentative_events],
    icon: RULE_SETTING_ICONS.tentative,
    off: skipMaybe,
  }
  const icon = RULE_SETTING_ICONS.unanswered
  if (detail.unanswered_invitations === "wait") return [maybe, { text: t("rulePreview.rule.unansweredWait"), icon, off: false }]
  return [
    maybe,
    { text: skipMaybe ? t("rulePreview.rule.unansweredOff") : t("rulePreview.rule.unansweredAs"), icon, off: skipMaybe },
  ]
}

/**
 * The rule's choices in a few words each, in the order Rule Details lists them: how events look,
 * then which events it includes. The privacy line above already says what the destination sees.
 */
function settingsFacts(i18n: I18n, detail: RuleDetail): SettingFact[] {
  const { t } = i18n
  return [
    ...invitationFacts(i18n, detail),
    { text: t("rulePreview.rule.declinedOff"), icon: RULE_SETTING_ICONS.declined, off: true },
    {
      text: detail.sync_all_day_events ? t("rulePreview.rule.allDayOn") : t("rulePreview.rule.allDayOff"),
      icon: RULE_SETTING_ICONS.allDay,
      off: !detail.sync_all_day_events,
    },
    {
      text: detail.sync_birthdays ? t("rulePreview.rule.birthdaysOn") : t("rulePreview.rule.birthdaysOff"),
      icon: RULE_SETTING_ICONS.birthdays,
      off: !detail.sync_birthdays,
    },
    { text: t("rulePreview.rule.since", { count: detail.initial_lookback_days }), icon: RULE_SETTING_ICONS.startingPoint, off: false },
  ]
}

/**
 * The choices this preview follows, as a quiet wrapping list under the privacy line, each with its
 * own icon, and the way to change them at its end.
 */
export function PreviewSettings({ detail, onChange }: { detail: RuleDetail; onChange: () => void }) {
  const i18n = useI18n()
  const { t } = i18n
  return (
    <div className="rule-preview-settings">
      <ul role="list" className="rule-preview-facts" aria-label={t("rulePreview.rule.settings")}>
        {settingsFacts(i18n, detail).map(({ text, icon: Icon, off }) => (
          <li key={text} className="rule-preview-fact" data-tone={off ? "off" : "on"}>
            <Icon aria-hidden="true" />
            {text}
          </li>
        ))}
      </ul>
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
    </div>
  )
}
