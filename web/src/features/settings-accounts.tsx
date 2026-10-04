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
import { accountSummary } from "@/lib/account-summary"
import { type ConnectedAccount, api } from "@/lib/api"
import { recordAuthorizationStart } from "@/lib/oauth-redirect"
import { type AccountCommands, useAccountCommands } from "@/lib/use-account-commands"
import type { GoogleReturn } from "@/lib/use-google-return"
import { AccountRow } from "@/features/settings-account-row"
import { GoogleReturnNote, GoogleReturnStep } from "@/features/settings-google-return"

const CONNECTION_STEPS: { title: MessageKey; body: MessageKey }[] = [
  { title: "settings.connectionGuide.connect.title", body: "settings.connectionGuide.connect.body" },
  { title: "settings.connectionGuide.choose.title", body: "settings.connectionGuide.choose.body" },
  { title: "settings.connectionGuide.preview.title", body: "settings.connectionGuide.preview.body" },
]

function ConnectionGuide({ googleConfigured }: { googleConfigured: boolean }) {
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
        {googleConfigured ? (
          <p className="connection-guide-note">{t("settings.connectionGuide.ready")}</p>
        ) : (
          <p className="connection-guide-note">{rich(t("settings.connectionGuide.notConfigured"), { code: codeTag })}</p>
        )}
      </div>
    </details>
  )
}

export function AccountsSection({
  googleConfigured,
  justConnected,
  returnHelp,
}: {
  googleConfigured: boolean
  justConnected: boolean
  returnHelp: GoogleReturn
}) {
  const { t } = useI18n()
  const [accountsChoice, setAccountsChoice] = useState<boolean | null>(null)
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: api.accounts })
  const commands = useAccountCommands(accounts.data)

  return (
    <section className="settings-section" aria-labelledby="accounts-title">
      <AccountsHeading googleConfigured={googleConfigured} hasAccounts={Boolean(accounts.data?.length)} />

      {!googleConfigured && (
        <p className="settings-note" role="status">
          {rich(t("settings.accounts.notConfiguredNote"), { code: codeTag })}
        </p>
      )}
      <GoogleReturnStep help={returnHelp} />
      <ConnectionGuide googleConfigured={googleConfigured} />
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
          googleConfigured={googleConfigured}
          returnHelp={returnHelp}
          commands={commands}
        />
      )}
      <AccountFeedback commands={commands} />
    </section>
  )
}

function AccountsHeading({ googleConfigured, hasAccounts }: { googleConfigured: boolean; hasAccounts: boolean }) {
  const { t } = useI18n()
  return (
    <div className="section-heading">
      <div>
        <h2 id="accounts-title">{t("settings.accounts.title")}</h2>
        <p>{t("settings.accounts.intro")}</p>
      </div>
      {googleConfigured ? (
        // The next step only while nothing is connected; otherwise a routine addition.
        <Button variant={hasAccounts ? "outline" : "default"} asChild>
          <a href="/api/v1/oauth/google/start" onClick={() => recordAuthorizationStart()}>
            <Plus aria-hidden="true" /> {t("settings.accounts.connect")}
          </a>
        </Button>
      ) : (
        <Badge variant="attention"><ShieldAlert aria-hidden="true" /> {t("settings.accounts.notConfigured")}</Badge>
      )}
    </div>
  )
}

function AccountGroup({
  accounts,
  choice,
  onChoose,
  justConnected,
  googleConfigured,
  returnHelp,
  commands,
}: {
  accounts: ConnectedAccount[]
  choice: boolean | null
  onChoose: (open: boolean) => void
  justConnected: boolean
  googleConfigured: boolean
  returnHelp: GoogleReturn
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
            <AccountList accounts={accounts} googleConfigured={googleConfigured} commands={commands} />
          )}
        </>
      )}
      <GoogleReturnNote help={returnHelp} className="account-group-footer" />
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
  googleConfigured,
  commands,
}: {
  accounts: ConnectedAccount[]
  googleConfigured: boolean
  commands: AccountCommands
}) {
  const names = accounts.map((account) => account.display_name)
  const sharedNames = new Set(names.filter((name, index) => names.indexOf(name) !== index))
  return (
    <ul className="account-list" id="account-list">
      {accounts.map((account) => (
        <AccountRow
          key={account.id}
          account={account}
          sharedName={sharedNames.has(account.display_name)}
          googleConfigured={googleConfigured}
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
