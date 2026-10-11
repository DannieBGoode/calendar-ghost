import { CheckCircle2, KeyRound, ShieldAlert, ShieldCheck, Trash2, Unplug } from "lucide-react"

import { AccountAvatar } from "@/components/account-avatar"
import { OverflowMenu } from "@/components/overflow-menu"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import { needsReauthorization } from "@/lib/account-summary"
import type { CalendarProvider, ConnectedAccount } from "@/lib/api"
import { recordAuthorizationStart } from "@/lib/oauth-redirect"
import { accountNoun, connectUrl } from "@/lib/providers"
import type { AccessCheck, AccountCommands } from "@/lib/use-account-commands"

function ruleUsage({ t }: I18n, count: number, authorized: boolean): string {
  if (count === 0) return t("settings.accounts.usage.none")
  return authorized ? t("settings.accounts.usage.used", { count }) : t("settings.accounts.usage.stopped", { count })
}

/** Brings the account a stopped rule pointed to into view, and to the keyboard. */
function revealAccount(row: HTMLLIElement | null) {
  row?.scrollIntoView({ block: "center" })
  row?.focus({ preventScroll: true })
}

export function AccountRow({
  account,
  sharedName,
  provider,
  focused,
  commands,
}: {
  account: ConnectedAccount
  sharedName: boolean
  /** The account's provider, while Users can connect it here; null otherwise. */
  provider: CalendarProvider | null
  /** The account a stopped rule or a provider's return pointed to. */
  focused: boolean
  commands: AccountCommands
}) {
  const connected = account.state === "connected"
  const authorized = !needsReauthorization(account)
  return (
    <li
      className="account-item"
      id={`account-${account.id}`}
      data-focused={focused || undefined}
      tabIndex={focused ? -1 : undefined}
      ref={focused ? revealAccount : undefined}
    >
      <div className="account-main">
        <AccountIdentity account={account} sharedName={sharedName} authorized={authorized} />
        <div className="account-actions">
          <AccountStateBadge account={account} />
          {connected ? (
            <ConnectedAccountActions account={account} provider={provider} commands={commands} />
          ) : (
            <DisconnectedAccountActions account={account} provider={provider} commands={commands} />
          )}
        </div>
      </div>
      <AccountRowNotes account={account} commands={commands} />
    </li>
  )
}

/** What the row says below its actions: a check's result, or a confirmation. */
function AccountRowNotes({ account, commands }: { account: ConnectedAccount; commands: AccountCommands }) {
  const i18n = useI18n()
  const { verifyAccess } = commands
  const access = commands.accessChecks[account.id]
  const checkFailed = verifyAccess.error !== null && verifyAccess.variables === account.id
  return (
    <>
      {access && <AccessResult access={access} />}
      {checkFailed && (
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
    </>
  )
}

function AccountIdentity({
  account,
  sharedName,
  authorized,
}: {
  account: ConnectedAccount
  sharedName: boolean
  authorized: boolean
}) {
  const i18n = useI18n()
  return (
    <div className="account-identity">
      <AccountAvatar
        displayName={account.display_name}
        email={account.email}
        avatarUrl={account.avatar_url}
        provider={account.provider}
      />
      <div className="account-copy">
        {/* One person often connects several accounts under the same name, so the address
            leads when the name alone would not tell them apart. */}
        <h3>{sharedName ? account.email : account.display_name}</h3>
        <p>
          {i18n.t("settings.accounts.providerAndAddress", {
            account: accountNoun(i18n, account.provider),
            address: sharedName ? account.display_name : account.email,
          })}
        </p>
        <span data-stopped={!authorized && account.rule_count > 0 ? "" : undefined}>
          {ruleUsage(i18n, account.rule_count, authorized)}
        </span>
      </div>
    </div>
  )
}

/**
 * A disconnected account, or one its provider stopped accepting, stops every rule that uses it
 * until it is reauthorized.
 */
function AccountStateBadge({ account }: { account: ConnectedAccount }) {
  const { t } = useI18n()
  if (!needsReauthorization(account)) {
    return (
      <Badge variant="healthy">
        <CheckCircle2 aria-hidden="true" /> {t("settings.accounts.state.connected")}
      </Badge>
    )
  }
  return (
    <Badge variant={account.rule_count > 0 ? "stopped" : "attention"}>
      <ShieldAlert aria-hidden="true" />
      {account.state === "connected" ? t("settings.accounts.state.lapsed") : t("settings.accounts.state.disconnected")}
    </Badge>
  )
}

/** The provider's consent for this account, which it offers first; the row's fix when access is gone. */
function ReauthorizeButton({ account, provider }: { account: ConnectedAccount; provider: CalendarProvider | null }) {
  const { t } = useI18n()
  // The row's fix, so it stays visible even before its provider is configured.
  if (!provider) {
    return (
      <Button className="account-action" disabled title={t("settings.accounts.actions.reauthorizeUnavailable")}>
        <KeyRound aria-hidden="true" /> {t("settings.accounts.actions.reauthorize")}
      </Button>
    )
  }
  return (
    <Button className="account-action" asChild>
      <a href={connectUrl(provider, account.id)} onClick={() => recordAuthorizationStart(provider.kind)}>
        <KeyRound aria-hidden="true" /> {t("settings.accounts.actions.reauthorize")}
      </a>
    </Button>
  )
}

function ConnectedAccountActions({
  account,
  provider,
  commands,
}: {
  account: ConnectedAccount
  provider: CalendarProvider | null
  commands: AccountCommands
}) {
  const { t } = useI18n()
  const { verifyAccess, disconnect, permanentDelete } = commands
  const confirming = commands.confirmingAccountId === account.id
  const checking = verifyAccess.isPending && verifyAccess.variables === account.id
  return (
    <>
      {needsReauthorization(account) && <ReauthorizeButton account={account} provider={provider} />}
      <Button
        className="account-action"
        variant="outline"
        onClick={() => commands.checkAccess(account.id)}
        disabled={disconnect.isPending || permanentDelete.isPending || verifyAccess.isPending}
      >
        <ShieldCheck aria-hidden="true" />
        {checking ? t("settings.accounts.actions.checkingAccess") : t("settings.accounts.actions.checkAccess")}
      </Button>
      {/* Rare and disruptive, so it waits in the row's menu beside the everyday actions. */}
      <OverflowMenu
        label={t("settings.accounts.actions.more", { email: account.email })}
        items={[
          {
            id: "disconnect",
            label: t("settings.accounts.actions.disconnect"),
            description: t("settings.accounts.actions.disconnectHint"),
            disabled: confirming || disconnect.isPending || permanentDelete.isPending || verifyAccess.isPending,
            onSelect: () => commands.confirmDisconnect(account.id),
          },
        ]}
      />
    </>
  )
}

function DisconnectedAccountActions({
  account,
  provider,
  commands,
}: {
  account: ConnectedAccount
  provider: CalendarProvider | null
  commands: AccountCommands
}) {
  const { t } = useI18n()
  const { disconnect, permanentDelete } = commands
  const deleting = commands.deletingAccountId === account.id
  return (
    <>
      <ReauthorizeButton account={account} provider={provider} />
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
        {access.rules_resumed > 0 && (
          <p>{t("settings.accounts.access.resumed", { count: access.rules_resumed })}</p>
        )}
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
