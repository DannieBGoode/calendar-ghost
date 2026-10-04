import { CheckCircle2, KeyRound, ShieldAlert, ShieldCheck, Trash2, Unplug } from "lucide-react"

import { AccountAvatar } from "@/components/account-avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import type { ConnectedAccount } from "@/lib/api"
import { recordAuthorizationStart } from "@/lib/oauth-redirect"
import type { AccessCheck, AccountCommands } from "@/lib/use-account-commands"

function ruleUsage({ t }: I18n, count: number, connected: boolean): string {
  if (count === 0) return t("settings.accounts.usage.none")
  return connected ? t("settings.accounts.usage.used", { count }) : t("settings.accounts.usage.stopped", { count })
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
  const i18n = useI18n()
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
          {apiErrorMessage(i18n, verifyAccess.error)}
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
  const i18n = useI18n()
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
          {ruleUsage(i18n, account.rule_count, connected)}
        </span>
      </div>
    </div>
  )
}

/** A disconnected account stops every rule that uses it until it is reauthorized. */
function AccountStateBadge({ account, connected }: { account: ConnectedAccount; connected: boolean }) {
  const { t } = useI18n()
  return (
    <Badge variant={connected ? "healthy" : account.rule_count > 0 ? "stopped" : "attention"}>
      {connected ? (
        <CheckCircle2 aria-hidden="true" />
      ) : (
        <ShieldAlert aria-hidden="true" />
      )}
      {connected ? t("settings.accounts.state.connected") : t("settings.accounts.state.disconnected")}
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
  const { t } = useI18n()
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
        {checking ? t("settings.accounts.actions.checkingAccess") : t("settings.accounts.actions.checkAccess")}
      </Button>
      <Button
        className="account-action"
        variant="ghost"
        onClick={() => commands.confirmDisconnect(account.id)}
        disabled={disconnect.isPending || permanentDelete.isPending || verifyAccess.isPending}
        aria-expanded={confirming}
        aria-controls={confirming ? `disconnect-${account.id}` : undefined}
      >
        <Unplug aria-hidden="true" /> {t("settings.accounts.actions.disconnect")}
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
  const { t } = useI18n()
  const { disconnect, permanentDelete } = commands
  const deleting = commands.deletingAccountId === account.id
  return (
    <>
      {/* The row's fix, so it stays visible even before Google is configured. */}
      {googleConfigured ? (
        <Button className="account-action" asChild>
          <a href="/api/v1/oauth/google/start" onClick={() => recordAuthorizationStart()}>
            <KeyRound aria-hidden="true" /> {t("settings.accounts.actions.reauthorize")}
          </a>
        </Button>
      ) : (
        <Button
          className="account-action"
          disabled
          title={t("settings.accounts.actions.reauthorizeUnavailable")}
        >
          <KeyRound aria-hidden="true" /> {t("settings.accounts.actions.reauthorize")}
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
        <Trash2 aria-hidden="true" /> {t("settings.accounts.actions.delete")}
      </Button>
    </>
  )
}

function AccessResult({ access }: { access: AccessCheck }) {
  const { t } = useI18n()
  return (
    <div className="account-access-result" role="status">
      <ShieldCheck aria-hidden="true" />
      <div>
        <h4>{t("settings.accounts.access.title")}</h4>
        <p>
          {t(
            access.writable_calendars === 0 ? "settings.accounts.access.bodySourceOnly" : "settings.accounts.access.body",
            { count: access.calendars_visible, writable: access.writable_calendars },
          )}
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
  const { t } = useI18n()
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
          {t("settings.accounts.disconnect.title", { name: account.display_name })}
        </h4>
        <p>
          {account.rule_count > 0
            ? t("settings.accounts.disconnect.bodyWithRules", { count: account.rule_count })
            : t("settings.accounts.disconnect.bodyWithoutRules")}
        </p>
      </div>
      <div className="confirmation-actions">
        <Button
          variant="outline"
          onClick={() => commands.setConfirmingAccountId(null)}
          disabled={disconnect.isPending}
        >
          {t("settings.accounts.actions.keep")}
        </Button>
        <Button
          variant="destructive"
          onClick={() => disconnect.mutate(account.id)}
          disabled={disconnect.isPending}
        >
          <Unplug aria-hidden="true" />
          {disconnect.isPending ? t("settings.accounts.disconnect.pending") : t("settings.accounts.actions.disconnect")}
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
  const { t } = useI18n()
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
          {t("settings.accounts.delete.title", { name: account.display_name })}
        </h4>
        <p>
          {account.rule_count > 0
            ? t("settings.accounts.delete.bodyWithRules", { count: account.rule_count })
            : t("settings.accounts.delete.bodyWithoutRules")}
        </p>
      </div>
      <div className="confirmation-actions">
        <Button
          variant="outline"
          onClick={() => commands.setDeletingAccountId(null)}
          disabled={permanentDelete.isPending}
        >
          {t("settings.accounts.actions.keep")}
        </Button>
        <Button
          variant="destructive"
          onClick={() => permanentDelete.mutate(account.id)}
          disabled={permanentDelete.isPending}
        >
          <Trash2 aria-hidden="true" />
          {permanentDelete.isPending ? t("settings.accounts.delete.pending") : t("settings.accounts.delete.confirm")}
        </Button>
      </div>
    </div>
  )
}
