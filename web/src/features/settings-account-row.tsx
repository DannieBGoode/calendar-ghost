import { CheckCircle2, KeyRound, ShieldAlert, ShieldCheck, Trash2, Unplug } from "lucide-react"

import { AccountAvatar } from "@/components/account-avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import type { ConnectedAccount } from "@/lib/api"
import { recordAuthorizationStart } from "@/lib/oauth-redirect"
import type { AccessCheck, AccountCommands } from "@/lib/use-account-commands"

function ruleUsage(count: number, connected: boolean): string {
  if (count === 0) return "Not used by any rule"
  const rules = `${count} rule${count === 1 ? "" : "s"}`
  return connected ? `Used by ${rules}` : `${rules} stopped until it is reauthorized`
}

export function AccountRow({
  account,
  sharedName,
  googleConfigured,
  commands,
}: {
  account: ConnectedAccount
  sharedName: boolean
  googleConfigured: boolean
  commands: AccountCommands
}) {
  const { verifyAccess } = commands
  const connected = account.state === "connected"
  const access = commands.accessChecks[account.id]
  return (
    <li className="account-item">
      <div className="account-main">
        <AccountIdentity account={account} sharedName={sharedName} connected={connected} />
        <div className="account-actions">
          <AccountStateBadge account={account} connected={connected} />
          {connected ? (
            <ConnectedAccountActions account={account} commands={commands} />
          ) : (
            <DisconnectedAccountActions
              account={account}
              googleConfigured={googleConfigured}
              commands={commands}
            />
          )}
        </div>
      </div>
      {access && <AccessResult access={access} />}
      {verifyAccess.error && verifyAccess.variables === account.id && (
        <div className="inline-error account-access-error" role="alert">
          {verifyAccess.error.message}
        </div>
      )}
      {commands.confirmingAccountId === account.id && (
        <DisconnectConfirmation account={account} commands={commands} />
      )}
      {commands.deletingAccountId === account.id && (
        <DeleteConfirmation account={account} commands={commands} />
      )}
    </li>
  )
}

function AccountIdentity({
  account,
  sharedName,
  connected,
}: {
  account: ConnectedAccount
  sharedName: boolean
  connected: boolean
}) {
  return (
    <div className="account-identity">
      <AccountAvatar
        displayName={account.display_name}
        email={account.email}
        avatarUrl={account.avatar_url}
      />
      <div className="account-copy">
        {/* One person often connects several Google accounts under the same name, so the
            address leads when the name alone would not tell them apart. */}
        <h3>{sharedName ? account.email : account.display_name}</h3>
        <p>{sharedName ? account.display_name : account.email}</p>
        <span data-stopped={!connected && account.rule_count > 0 ? "" : undefined}>
          {ruleUsage(account.rule_count, connected)}
        </span>
      </div>
    </div>
  )
}

/** A disconnected account stops every rule that uses it until it is reauthorized. */
function AccountStateBadge({ account, connected }: { account: ConnectedAccount; connected: boolean }) {
  return (
    <Badge variant={connected ? "healthy" : account.rule_count > 0 ? "stopped" : "attention"}>
      {connected ? (
        <CheckCircle2 aria-hidden="true" />
      ) : (
        <ShieldAlert aria-hidden="true" />
      )}
      {connected ? "Connected" : "Disconnected"}
    </Badge>
  )
}

function ConnectedAccountActions({
  account,
  commands,
}: {
  account: ConnectedAccount
  commands: AccountCommands
}) {
  const { verifyAccess, disconnect, permanentDelete } = commands
  const confirming = commands.confirmingAccountId === account.id
  const checking = verifyAccess.isPending && verifyAccess.variables === account.id
  return (
    <>
      <Button
        className="account-action"
        variant="outline"
        onClick={() => commands.checkAccess(account.id)}
        disabled={disconnect.isPending || permanentDelete.isPending || verifyAccess.isPending}
      >
        <ShieldCheck aria-hidden="true" />
        {checking ? "Checking access…" : "Check access"}
      </Button>
      <Button
        className="account-action"
        variant="ghost"
        onClick={() => commands.confirmDisconnect(account.id)}
        disabled={disconnect.isPending || permanentDelete.isPending || verifyAccess.isPending}
        aria-expanded={confirming}
        aria-controls={confirming ? `disconnect-${account.id}` : undefined}
      >
        <Unplug aria-hidden="true" /> Disconnect account
      </Button>
    </>
  )
}

function DisconnectedAccountActions({
  account,
  googleConfigured,
  commands,
}: {
  account: ConnectedAccount
  googleConfigured: boolean
  commands: AccountCommands
}) {
  const { disconnect, permanentDelete } = commands
  const deleting = commands.deletingAccountId === account.id
  return (
    <>
      {/* The row's fix, so it stays visible even before Google is configured. */}
      {googleConfigured ? (
        <Button className="account-action" asChild>
          <a href="/api/v1/oauth/google/start" onClick={() => recordAuthorizationStart()}>
            <KeyRound aria-hidden="true" /> Reauthorize account
          </a>
        </Button>
      ) : (
        <Button
          className="account-action"
          disabled
          title="Add the master key and Google OAuth credentials in .env, then restart."
        >
          <KeyRound aria-hidden="true" /> Reauthorize account
        </Button>
      )}
      <Button
        className="account-action account-delete-action"
        variant="ghost"
        onClick={() => commands.confirmPermanentDelete(account.id)}
        disabled={disconnect.isPending || permanentDelete.isPending}
        aria-expanded={deleting}
        aria-controls={deleting ? `delete-${account.id}` : undefined}
      >
        <Trash2 aria-hidden="true" /> Delete account
      </Button>
    </>
  )
}

function AccessResult({ access }: { access: AccessCheck }) {
  return (
    <div className="account-access-result" role="status">
      <ShieldCheck aria-hidden="true" />
      <div>
        <h4>Calendar API access confirmed</h4>
        <p>
          Calendar-list and event permissions are available. {access.calendars_visible} calendar
          {access.calendars_visible === 1 ? " is" : "s are"} visible and {access.writable_calendars} can be used as a destination.
          {access.writable_calendars === 0
            ? " This account can still be used as a source."
            : ""}
        </p>
      </div>
    </div>
  )
}

function DisconnectConfirmation({
  account,
  commands,
}: {
  account: ConnectedAccount
  commands: AccountCommands
}) {
  const { disconnect } = commands
  return (
    <div
      className="disconnect-confirmation"
      id={`disconnect-${account.id}`}
      role="group"
      aria-labelledby={`disconnect-title-${account.id}`}
    >
      <div>
        <h4 id={`disconnect-title-${account.id}`}>
          Disconnect {account.display_name}?
        </h4>
        <p>
          Stored Google credentials will be removed. {account.rule_count > 0
            ? `${account.rule_count} affected rule${account.rule_count === 1 ? "" : "s"} will require reauthorization before they can run.`
            : "No Directional Sync Rules currently use this account."}
        </p>
      </div>
      <div className="confirmation-actions">
        <Button
          variant="outline"
          onClick={() => commands.setConfirmingAccountId(null)}
          disabled={disconnect.isPending}
        >
          Keep account
        </Button>
        <Button
          variant="destructive"
          onClick={() => disconnect.mutate(account.id)}
          disabled={disconnect.isPending}
        >
          <Unplug aria-hidden="true" />
          {disconnect.isPending ? "Disconnecting…" : "Disconnect account"}
        </Button>
      </div>
    </div>
  )
}

function DeleteConfirmation({
  account,
  commands,
}: {
  account: ConnectedAccount
  commands: AccountCommands
}) {
  const { permanentDelete } = commands
  return (
    <div
      className="disconnect-confirmation delete-confirmation"
      id={`delete-${account.id}`}
      role="group"
      aria-labelledby={`delete-title-${account.id}`}
    >
      <div>
        <h4 id={`delete-title-${account.id}`}>
          Delete {account.display_name} permanently?
        </h4>
        <p>
          This cannot be undone. The account record
          {account.rule_count > 0
            ? ` and ${account.rule_count} affected Directional Sync Rule${account.rule_count === 1 ? "" : "s"}, including their mappings, cursors, incidents, and audit activity,`
            : ""} will be removed. {account.rule_count > 0
            ? "Existing Managed Projections in Google Calendar will not be deleted and will no longer be managed."
            : "No Directional Sync Rules currently use this account."}
        </p>
      </div>
      <div className="confirmation-actions">
        <Button
          variant="outline"
          onClick={() => commands.setDeletingAccountId(null)}
          disabled={permanentDelete.isPending}
        >
          Keep account
        </Button>
        <Button
          variant="destructive"
          onClick={() => permanentDelete.mutate(account.id)}
          disabled={permanentDelete.isPending}
        >
          <Trash2 aria-hidden="true" />
          {permanentDelete.isPending ? "Deleting…" : "Delete permanently"}
        </Button>
      </div>
    </div>
  )
}
