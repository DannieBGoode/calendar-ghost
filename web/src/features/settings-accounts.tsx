import { useQuery } from "@tanstack/react-query"
import { CheckCircle2, ChevronDown, CircleUserRound, KeyRound, Plus, ShieldAlert } from "lucide-react"
import { useState } from "react"

import { AccountAvatar } from "@/components/account-avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { accountSummary } from "@/lib/account-summary"
import { type ConnectedAccount, api } from "@/lib/api"
import { recordAuthorizationStart } from "@/lib/oauth-redirect"
import { type AccountCommands, useAccountCommands } from "@/lib/use-account-commands"
import type { GoogleReturn } from "@/lib/use-google-return"
import { AccountRow } from "@/features/settings-account-row"
import { GoogleReturnNote, GoogleReturnStep } from "@/features/settings-google-return"

function ConnectionGuide({ googleConfigured }: { googleConfigured: boolean }) {
  return (
    <details className="inline-help connection-guide">
      <summary>
        <KeyRound aria-hidden="true" />
        <span>How connecting works</span>
        <ChevronDown className="inline-help-chevron" aria-hidden="true" />
      </summary>
      <div className="inline-help-body connection-guide-body">
        <ol className="connection-guide-steps">
          <li>
            <strong>Connect a Google account</strong>
            <span>Authorize calendar discovery and event access for one account.</span>
          </li>
          <li>
            <strong>Choose calendars</strong>
            <span>Create a Directional Sync Rule with one source and one destination.</span>
          </li>
          <li>
            <strong>Preview before syncing</strong>
            <span>Review what will be written before anything reaches the destination.</span>
          </li>
        </ol>
        {googleConfigured ? (
          <p className="connection-guide-note">Use the Connect Google account button above to begin.</p>
        ) : (
          <p className="connection-guide-note">
            Add the master key and Google OAuth credentials in <code>.env</code>, then restart before connecting.
          </p>
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
  const [accountsChoice, setAccountsChoice] = useState<boolean | null>(null)
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: api.accounts })
  const commands = useAccountCommands(accounts.data)

  return (
    <section className="settings-section" aria-labelledby="accounts-title">
      <AccountsHeading googleConfigured={googleConfigured} hasAccounts={Boolean(accounts.data?.length)} />

      {!googleConfigured && (
        <p className="settings-note" role="status">
          Add the master key and Google OAuth credentials in <code>.env</code>, then restart
          before connecting an account.
        </p>
      )}
      <GoogleReturnStep help={returnHelp} />
      <ConnectionGuide googleConfigured={googleConfigured} />
      {accounts.isPending && (
        <div className="account-list-loading" aria-label="Loading connected accounts">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      )}
      {accounts.error && (
        <div className="inline-error" role="alert">
          Connected accounts could not be loaded. Reload the page and try again.
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
  return (
    <div className="section-heading">
      <div>
        <h2 id="accounts-title">Connected accounts</h2>
        <p>The Google accounts whose calendars your rules can read and write.</p>
      </div>
      {googleConfigured ? (
        // The next step only while nothing is connected; otherwise a routine addition.
        <Button variant={hasAccounts ? "outline" : "default"} asChild>
          <a href="/api/v1/oauth/google/start" onClick={() => recordAuthorizationStart()}>
            <Plus aria-hidden="true" /> Connect Google account
          </a>
        </Button>
      ) : (
        <Badge variant="attention"><ShieldAlert aria-hidden="true" /> Not configured</Badge>
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
  const summary = accountSummary(accounts)
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
            <h3>No Google accounts connected</h3>
            <p>Connect an account to choose its calendars for your rules.</p>
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
          {accounts.map((account) => account.email).join(", ")}
        </span>
      </span>
      <span className="account-summary-toggle">
        {open ? "Hide" : "Show"}
        <span className="sr-only"> accounts</span>
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
  const { statusMessage, disconnect, permanentDelete } = commands
  return (
    <>
      {statusMessage && <p className="account-status-message" role="status">{statusMessage}</p>}
      {disconnect.error && (
        <div className="inline-error" role="alert">
          {disconnect.error.message}
        </div>
      )}
      {permanentDelete.error && (
        <div className="inline-error" role="alert">
          {permanentDelete.error.message}
        </div>
      )}
    </>
  )
}
