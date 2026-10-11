import { useQuery } from "@tanstack/react-query"
import { CheckCircle2, ChevronDown, CircleUserRound, KeyRound, Plus, ShieldAlert } from "lucide-react"
import { useState } from "react"

import { AccountAvatar } from "@/components/account-avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { codeTag, rich } from "@/i18n/rich"
import type { MessageKey } from "@/i18n/types"
import { accountSummary, needsReauthorization } from "@/lib/account-summary"
import { type CalendarProvider, type ConnectedAccount, api } from "@/lib/api"
import { recordAuthorizationStart } from "@/lib/oauth-redirect"
import { accountNoun, connectUrl, providerOf } from "@/lib/providers"
import { type AccountCommands, useAccountCommands } from "@/lib/use-account-commands"
import type { OAuthReturn } from "@/lib/use-oauth-return"
import { AccountRow } from "@/features/settings-account-row"
import { OAuthReturnNote, OAuthReturnStep } from "@/features/settings-oauth-return"

const CONNECTION_STEPS: { title: MessageKey; body: MessageKey }[] = [
  { title: "settings.connectionGuide.connect.title", body: "settings.connectionGuide.connect.body" },
  { title: "settings.connectionGuide.choose.title", body: "settings.connectionGuide.choose.body" },
  { title: "settings.connectionGuide.preview.title", body: "settings.connectionGuide.preview.body" },
]

function ConnectionGuide({ configured }: { configured: boolean }) {
  const { t } = useI18n()
  return (
    <details className="inline-help connection-guide">
      <summary>
        <KeyRound aria-hidden="true" />
        <span>{t("settings.connectionGuide.summary")}</span>
        <ChevronDown className="inline-help-chevron" aria-hidden="true" />
      </summary>
      <div className="inline-help-body connection-guide-body">
        <ol className="connection-guide-steps">
          {CONNECTION_STEPS.map((step) => (
            <li key={step.title}>
              <strong>{t(step.title)}</strong>
              <span>{t(step.body)}</span>
            </li>
          ))}
        </ol>
        {configured ? (
          <p className="connection-guide-note">{t("settings.connectionGuide.ready")}</p>
        ) : (
          <p className="connection-guide-note">{rich(t("settings.connectionGuide.notConfigured"), { code: codeTag })}</p>
        )}
      </div>
    </details>
  )
}

export function AccountsSection({
  providers,
  justConnected,
  focusAccountId,
  returnHelp,
}: {
  /** The providers Users can connect here. */
  providers: CalendarProvider[]
  justConnected: boolean
  /** The account a stopped rule or a provider's return pointed to, shown open and in view. */
  focusAccountId: string | null
  returnHelp: OAuthReturn
}) {
  const { t } = useI18n()
  const [accountsChoice, setAccountsChoice] = useState<boolean | null>(null)
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: api.accounts })
  const commands = useAccountCommands(accounts.data)

  return (
    <section className="settings-section" aria-labelledby="accounts-title">
      <AccountsHeading providers={providers} hasAccounts={Boolean(accounts.data?.length)} />

      {providers.length === 0 && (
        <p className="settings-note" role="status">
          {rich(t("settings.accounts.notConfiguredNote"), { code: codeTag })}
        </p>
      )}
      <OAuthReturnStep help={returnHelp} />
      <ConnectionGuide configured={providers.length > 0} />
      {accounts.isPending && (
        <div className="account-list-loading" aria-label={t("settings.accounts.loading")}>
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      )}
      {accounts.error && (
        <div className="inline-error" role="alert">
          {t("settings.accounts.loadError")}
        </div>
      )}
      {accounts.data && (
        <AccountGroup
          accounts={accounts.data}
          choice={accountsChoice}
          onChoose={setAccountsChoice}
          justConnected={justConnected}
          focusAccountId={focusAccountId}
          providers={providers}
          returnHelp={returnHelp}
          commands={commands}
        />
      )}
      <AccountFeedback commands={commands} />
    </section>
  )
}

function AccountsHeading({ providers, hasAccounts }: { providers: CalendarProvider[]; hasAccounts: boolean }) {
  const { t } = useI18n()
  return (
    <div className="section-heading">
      <div>
        <h2 id="accounts-title">{t("settings.accounts.title")}</h2>
        <p>{t("settings.accounts.intro")}</p>
      </div>
      {providers.length > 0 ? (
        <div className="connect-actions">
          {providers.map((provider) => (
            <ConnectButton key={provider.kind} provider={provider} primary={!hasAccounts} />
          ))}
        </div>
      ) : (
        <Badge variant="attention"><ShieldAlert aria-hidden="true" /> {t("settings.accounts.notConfigured")}</Badge>
      )}
    </div>
  )
}

/** Starts connecting an account of one provider; the next step only while nothing is connected. */
function ConnectButton({ provider, primary }: { provider: CalendarProvider; primary: boolean }) {
  const i18n = useI18n()
  return (
    <Button variant={primary ? "default" : "outline"} asChild>
      <a href={connectUrl(provider)} onClick={() => recordAuthorizationStart(provider.kind)}>
        <Plus aria-hidden="true" /> {i18n.t("settings.accounts.connect", { account: accountNoun(i18n, provider.kind, [provider]) })}
      </a>
    </Button>
  )
}

function AccountGroup({
  accounts,
  choice,
  onChoose,
  justConnected,
  focusAccountId,
  providers,
  returnHelp,
  commands,
}: {
  accounts: ConnectedAccount[]
  choice: boolean | null
  onChoose: (open: boolean) => void
  justConnected: boolean
  focusAccountId: string | null
  providers: CalendarProvider[]
  returnHelp: OAuthReturn
  commands: AccountCommands
}) {
  const i18n = useI18n()
  const { t } = i18n
  const summary = accountSummary(i18n, accounts)
  // Collapsed while every account is healthy; open when one needs attention or just connected.
  const accountsOpen =
    choice ??
    Boolean(
      summary.needsAttention ||
        justConnected ||
        focusAccountId ||
        commands.confirmingAccountId ||
        commands.deletingAccountId,
    )
  return (
    <div className="account-group">
      {accounts.length === 0 ? (
        <div className="account-empty">
          <CircleUserRound aria-hidden="true" />
          <div>
            <h3>{t("settings.accounts.empty.title")}</h3>
            <p>{t("settings.accounts.empty.body")}</p>
          </div>
        </div>
      ) : (
        <>
          <AccountSummaryToggle
            accounts={accounts}
            summary={summary}
            open={accountsOpen}
            onToggle={() => onChoose(!accountsOpen)}
          />
          {accountsOpen && (
            <AccountList
              accounts={accounts}
              focusAccountId={focusAccountId}
              providers={providers}
              commands={commands}
            />
          )}
        </>
      )}
      <OAuthReturnNote help={returnHelp} className="account-group-footer" />
    </div>
  )
}

function AccountSummaryToggle({
  accounts,
  summary,
  open,
  onToggle,
}: {
  accounts: ConnectedAccount[]
  summary: ReturnType<typeof accountSummary>
  open: boolean
  onToggle: () => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  return (
    <button
      type="button"
      className="account-summary"
      aria-expanded={open}
      aria-controls={open ? "account-list" : undefined}
      onClick={onToggle}
    >
      <span className="account-stack">
        {accounts.slice(0, 3).map((account) => (
          <AccountAvatar
            key={account.id}
            displayName={account.display_name}
            email={account.email}
            avatarUrl={account.avatar_url}
            compact
          />
        ))}
      </span>
      <span className="account-summary-copy">
        <span
          className="account-summary-status"
          data-attention={summary.stopsRules ? "stopped" : summary.needsAttention ? "review" : undefined}
        >
          {summary.needsAttention ? (
            <ShieldAlert aria-hidden="true" />
          ) : (
            <CheckCircle2 aria-hidden="true" />
          )}
          {summary.text}
        </span>
        <span className="account-summary-emails">
          {i18n.format.unitList(accounts.map((account) => account.email))}
        </span>
      </span>
      <span className="account-summary-toggle">
        <span aria-hidden="true">
          {open ? t("settings.accounts.toggle.hide") : t("settings.accounts.toggle.show")}
        </span>
        <span className="sr-only">
          {open ? t("settings.accounts.toggle.hideAccounts") : t("settings.accounts.toggle.showAccounts")}
        </span>
        <ChevronDown aria-hidden="true" />
      </span>
    </button>
  )
}

function AccountList({
  accounts,
  focusAccountId,
  providers,
  commands,
}: {
  accounts: ConnectedAccount[]
  focusAccountId: string | null
  providers: CalendarProvider[]
  commands: AccountCommands
}) {
  const names = accounts.map((account) => account.display_name)
  const sharedNames = new Set(names.filter((name, index) => names.indexOf(name) !== index))
  // Accounts to reauthorize lead, so the fix is the first thing in the list.
  const ordered = [...accounts.filter(needsReauthorization), ...accounts.filter((a) => !needsReauthorization(a))]
  return (
    <ul className="account-list" id="account-list">
      {ordered.map((account) => (
        <AccountRow
          key={account.id}
          account={account}
          sharedName={sharedNames.has(account.display_name)}
          provider={providerOf(providers, account.provider)}
          focused={account.id === focusAccountId}
          commands={commands}
        />
      ))}
    </ul>
  )
}

function AccountFeedback({ commands }: { commands: AccountCommands }) {
  const i18n = useI18n()
  const { statusMessage, disconnect, permanentDelete } = commands
  return (
    <>
      {statusMessage && <p className="account-status-message" role="status">{statusMessage}</p>}
      {disconnect.error && (
        <div className="inline-error" role="alert">
          {apiErrorMessage(i18n, disconnect.error)}
        </div>
      )}
      {permanentDelete.error && (
        <div className="inline-error" role="alert">
          {apiErrorMessage(i18n, permanentDelete.error)}
        </div>
      )}
    </>
  )
}
