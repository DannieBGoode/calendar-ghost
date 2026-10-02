import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  CheckCircle2,
  ChevronDown,
  CircleUserRound,
  Download,
  Info,
  KeyRound,
  Plus,
  ShieldAlert,
  ShieldCheck,
  Trash2,
  Unplug,
} from "lucide-react"
import { useEffect, useId, useRef, useState } from "react"

import { AccountAvatar } from "@/components/account-avatar"
import { DestructiveConfirmation } from "@/components/destructive-confirmation"
import { LoadFailure } from "@/components/load-failure"
import { PageSkeleton } from "@/components/page-skeleton"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { NativeSelect } from "@/components/ui/native-select"
import { Skeleton } from "@/components/ui/skeleton"
import { useTheme } from "@/components/theme-provider"
import { accountSummary } from "@/lib/account-summary"
import { ApiError, STORAGE_LOGS_URL, api } from "@/lib/api"
import {
  authorizationAwaitingReturn,
  clearAuthorizationStart,
  oauthRedirectMismatch,
  oauthReturnAtCurrentOrigin,
  recordAuthorizationStart,
} from "@/lib/oauth-redirect"
import {
  activitySummary,
  canClearActivity,
  clearActivityConfirmation,
  clearedActivityMessage,
  countFailedConfirmation,
  logSummary,
} from "@/lib/storage"
import type { DarkPalette, ThemePreference } from "@/lib/theme"
import { cn } from "@/lib/utils"

type GoogleReturn = {
  mismatch: { redirectOrigin: string; redirectUri: string } | null
  awaiting: boolean
  dismiss: () => void
}

/**
 * Whether Google returns somewhere else, and whether a connection started in this browser may be
 * waiting for that return address. Read the OAuth outcome first: returning ends the attempt.
 */
function useGoogleReturn(redirectUri: string | null): GoogleReturn {
  const mismatch = oauthRedirectMismatch(redirectUri, window.location.origin)
  const [awaiting, setAwaiting] = useState(() => authorizationAwaitingReturn())
  return {
    mismatch: mismatch && redirectUri ? { redirectOrigin: mismatch.redirectOrigin, redirectUri } : null,
    awaiting,
    dismiss: () => {
      clearAuthorizationStart()
      setAwaiting(false)
    },
  }
}

/** The step that finishes a connection Google returned elsewhere; shown only while it can. */
function GoogleReturnStep({ help }: { help: GoogleReturn }) {
  const headingId = useId()
  if (!help.mismatch || !help.awaiting) return null
  return (
    <section className="oauth-feedback oauth-feedback-warning oauth-return" aria-labelledby={headingId}>
      <ShieldAlert aria-hidden="true" />
      <div>
        <h3 id={headingId}>Finish connecting your Google account</h3>
        <p>
          Google sends your browser to <code>{help.mismatch.redirectOrigin}</code> after you approve
          access. If that page did not load, copy its whole address from the address bar and paste it
          here. It works once, for 10 minutes.
        </p>
        <OAuthReturnForm redirectUri={help.mismatch.redirectUri} />
      </div>
      <Button variant="ghost" onClick={help.dismiss}>
        Dismiss
      </Button>
    </section>
  )
}

/** A quiet note that Google returns elsewhere, with the way to finish and the permanent fix. */
function GoogleReturnNote({ help, className }: { help: GoogleReturn; className?: string }) {
  if (!help.mismatch || help.awaiting) return null
  return (
    <details className={cn("inline-help", className)}>
      <summary>
        <Info aria-hidden="true" />
        <span>
          Google returns to <code>{help.mismatch.redirectOrigin}</code>, not this address
        </span>
        <ChevronDown className="inline-help-chevron" aria-hidden="true" />
      </summary>
      <div className="inline-help-body">
        <p>
          If its page does not load after you approve access, copy the whole address from the address
          bar and paste it here within 10 minutes to finish connecting.
        </p>
        <OAuthReturnForm redirectUri={help.mismatch.redirectUri} />
        <p>
          To stop this, set <code>CALENDAR_SYNC_GOOGLE_REDIRECT_URI</code> to an HTTPS address of this
          installation, for example with Tailscale Serve, and register it on your Google OAuth client.
          Opening Calendar Ghost at <code>{help.mismatch.redirectOrigin}</code>, for example through an
          SSH tunnel, also works.
        </p>
      </div>
    </details>
  )
}

export function GoogleReturnHelp({ redirectUri }: { redirectUri: string | null }) {
  const help = useGoogleReturn(redirectUri)
  return (
    <>
      <GoogleReturnStep help={help} />
      <GoogleReturnNote help={help} />
    </>
  )
}

function OAuthReturnForm({ redirectUri }: { redirectUri: string }) {
  const fieldId = useId()
  const [pasted, setPasted] = useState("")
  const [invalid, setInvalid] = useState(false)
  return (
    <form
      className="oauth-return-form"
      onSubmit={(event) => {
        event.preventDefault()
        const target = oauthReturnAtCurrentOrigin(pasted, redirectUri, window.location.origin)
        setInvalid(target === null)
        if (target) window.location.assign(target)
      }}
    >
      <Label htmlFor={fieldId}>Address Google returned to</Label>
      <div className="oauth-return-row">
        <Input
          id={fieldId}
          value={pasted}
          onChange={(event) => {
            setPasted(event.target.value)
            setInvalid(false)
          }}
          placeholder={`${redirectUri}?state=…`}
          aria-invalid={invalid}
          aria-describedby={invalid ? `${fieldId}-error` : undefined}
          autoComplete="off"
          spellCheck={false}
          required
        />
        <Button type="submit" variant="outline">
          Finish connecting
        </Button>
      </div>
      {invalid && (
        <p id={`${fieldId}-error`} className="field-error" role="alert">
          That is not the address Google returned to. Copy the whole address, starting with{" "}
          <code>{redirectUri}?</code>
        </p>
      )}
    </form>
  )
}

function ruleUsage(count: number): string {
  if (count === 0) return "Not used by any rule"
  return `Used by ${count} rule${count === 1 ? "" : "s"}`
}

export function SettingsPage() {
  const google = useQuery({ queryKey: ["google-configuration"], queryFn: api.googleConfiguration })
  if (google.isPending) return <PageSkeleton label="Loading settings" />
  if (google.error) return <LoadFailure title="Settings could not load" onRetry={() => void google.refetch()} />
  return <SettingsView googleConfigured={google.data.configured} redirectUri={google.data.redirect_uri} />
}

function SettingsView({
  googleConfigured,
  redirectUri,
}: {
  googleConfigured: boolean
  redirectUri: string | null
}) {
  const { preference, setPreference, darkPalette, setDarkPalette } = useTheme()
  const queryClient = useQueryClient()
  const [oauthOutcome] = useState(() => {
    const outcome = new URLSearchParams(window.location.search).get("google")
    if (outcome) clearAuthorizationStart()
    return outcome
  })
  const returnHelp = useGoogleReturn(redirectUri)
  const [accountsChoice, setAccountsChoice] = useState<boolean | null>(null)
  useEffect(() => {
    // A reload should not announce the same connection again.
    const url = new URL(window.location.href)
    if (!url.searchParams.has("google")) return
    url.searchParams.delete("google")
    window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`)
  }, [])
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: api.accounts })
  const [confirmingAccountId, setConfirmingAccountId] = useState<string | null>(null)
  const [deletingAccountId, setDeletingAccountId] = useState<string | null>(null)
  const [statusMessage, setStatusMessage] = useState("")
  const [accessChecks, setAccessChecks] = useState<
    Record<string, Awaited<ReturnType<typeof api.verifyAccountAccess>>>
  >({})
  const verifyAccess = useMutation({
    mutationFn: async (accountId: string) => ({
      accountId,
      access: await api.verifyAccountAccess(accountId),
    }),
    onSuccess: ({ accountId, access }) => {
      setAccessChecks((current) => ({ ...current, [accountId]: access }))
    },
  })
  const disconnect = useMutation({
    mutationFn: api.disconnectAccount,
    onSuccess: async (account) => {
      setConfirmingAccountId(null)
      setStatusMessage(`${account.display_name} was disconnected.`)
      setAccessChecks((current) => {
        const next = { ...current }
        delete next[account.id]
        return next
      })
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["accounts"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
        queryClient.invalidateQueries({ queryKey: ["rules"] }),
      ])
    },
  })
  const permanentDelete = useMutation({
    mutationFn: async (accountId: string) => {
      const account = accounts.data?.find((candidate) => candidate.id === accountId)
      await api.deleteAccount(accountId)
      return {
        accountId,
        displayName: account?.display_name ?? "The account",
        ruleCount: account?.rule_count ?? 0,
      }
    },
    onSuccess: async ({ accountId, displayName, ruleCount }) => {
      setDeletingAccountId(null)
      setStatusMessage(
        ruleCount > 0
          ? `${displayName} and ${ruleCount} affected Directional Sync Rule${ruleCount === 1 ? "" : "s"} were permanently deleted.`
          : `${displayName} was permanently deleted.`,
      )
      setAccessChecks((current) => {
        const next = { ...current }
        delete next[accountId]
        return next
      })
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["accounts"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
        queryClient.invalidateQueries({ queryKey: ["rules"] }),
        queryClient.invalidateQueries({ queryKey: ["activity"] }),
        queryClient.invalidateQueries({ queryKey: ["incidents"] }),
      ])
    },
  })

  const summary = accounts.data ? accountSummary(accounts.data) : null
  // Collapsed while every account is healthy; open when one needs attention or just connected.
  const accountsOpen =
    accountsChoice ??
    Boolean(
      summary?.needsAttention ||
        oauthOutcome === "connected" ||
        confirmingAccountId ||
        deletingAccountId,
    )

  function confirmDisconnect(accountId: string) {
    disconnect.reset()
    permanentDelete.reset()
    setStatusMessage("")
    setDeletingAccountId(null)
    setConfirmingAccountId(accountId)
  }

  function confirmPermanentDelete(accountId: string) {
    disconnect.reset()
    permanentDelete.reset()
    setStatusMessage("")
    setConfirmingAccountId(null)
    setDeletingAccountId(accountId)
  }

  function checkAccess(accountId: string) {
    verifyAccess.reset()
    setStatusMessage("")
    verifyAccess.mutate(accountId)
  }

  return (
    <div className="page-section settings-page">
      <div>
        <h1>Settings</h1>
        <p className="page-intro">
          Accounts and storage for this installation. Appearance applies to this browser only.
        </p>
      </div>

      {oauthOutcome === "connected" && (
        <div className="oauth-feedback oauth-feedback-success" role="status">
          <CheckCircle2 aria-hidden="true" />
          <div>
            <h2>Google account connected</h2>
            <p>Calendar permissions were confirmed and the account is ready for Directional Sync Rules.</p>
          </div>
        </div>
      )}
      {oauthOutcome === "calendar_permission_required" && (
        <div className="oauth-feedback oauth-feedback-warning" role="status">
          <ShieldAlert aria-hidden="true" />
          <div>
            <h2>Calendar access wasn’t granted</h2>
            <p>
              No account was connected. Calendar-list and event permissions are required to
              discover calendars and run Directional Sync Rules.
            </p>
          </div>
          {googleConfigured && (
            <Button variant="outline" asChild>
              <a href="/api/v1/oauth/google/start" onClick={() => recordAuthorizationStart()}>Try again</a>
            </Button>
          )}
        </div>
      )}
      {oauthOutcome === "authorization_failed" && (
        <div className="oauth-feedback oauth-feedback-warning" role="alert">
          <ShieldAlert aria-hidden="true" />
          <div>
            <h2>Google authorization could not be completed</h2>
            <p>The account was not connected. Try again, then use Check access to confirm permissions.</p>
          </div>
          {googleConfigured && (
            <Button variant="outline" asChild>
              <a href="/api/v1/oauth/google/start" onClick={() => recordAuthorizationStart()}>Try again</a>
            </Button>
          )}
        </div>
      )}

      <section className="settings-section" aria-labelledby="accounts-title">
        <div className="section-heading">
          <div>
            <h2 id="accounts-title">Connected accounts</h2>
            <p>The Google accounts whose calendars your rules can read and write.</p>
          </div>
          {googleConfigured ? (
            // The next step only while nothing is connected; otherwise a routine addition.
            <Button variant={accounts.data?.length ? "outline" : "default"} asChild>
              <a href="/api/v1/oauth/google/start" onClick={() => recordAuthorizationStart()}>
                <Plus aria-hidden="true" /> Connect Google account
              </a>
            </Button>
          ) : (
            <Badge variant="attention"><ShieldAlert aria-hidden="true" /> Not configured</Badge>
          )}
        </div>

        {!googleConfigured && (
          <p className="settings-note" role="status">
            Add the master key and Google OAuth credentials in <code>.env</code>, then restart
            before connecting an account.
          </p>
        )}
        <GoogleReturnStep help={returnHelp} />
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
          <div className="account-group">
            {accounts.data.length === 0 ? (
              <div className="account-empty">
                <CircleUserRound aria-hidden="true" />
                <div>
                  <h3>No Google accounts connected</h3>
                  <p>Connect an account to choose its calendars for your rules.</p>
                </div>
              </div>
            ) : (
              <>
                <button
                  type="button"
                  className="account-summary"
                  aria-expanded={accountsOpen}
                  aria-controls={accountsOpen ? "account-list" : undefined}
                  onClick={() => setAccountsChoice(!accountsOpen)}
                >
                  <span className="account-stack">
                    {accounts.data.slice(0, 3).map((account) => (
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
                      data-attention={summary?.needsAttention || undefined}
                    >
                      {summary?.needsAttention ? (
                        <ShieldAlert aria-hidden="true" />
                      ) : (
                        <CheckCircle2 aria-hidden="true" />
                      )}
                      {summary?.text}
                    </span>
                    <span className="account-summary-emails">
                      {accounts.data.map((account) => account.email).join(", ")}
                    </span>
                  </span>
                  <span className="account-summary-toggle">
                    {accountsOpen ? "Hide" : "Show"}
                    <span className="sr-only"> accounts</span>
                    <ChevronDown aria-hidden="true" />
                  </span>
                </button>
                {accountsOpen && (
                  <ul className="account-list" id="account-list">
            {accounts.data.map((account) => {
              const connected = account.state === "connected"
              const confirming = confirmingAccountId === account.id
              const deleting = deletingAccountId === account.id
              const access = accessChecks[account.id]
              const checking = verifyAccess.isPending && verifyAccess.variables === account.id
              return (
                <li className="account-item" key={account.id}>
                  <div className="account-main">
                    <div className="account-identity">
                      <AccountAvatar
                        displayName={account.display_name}
                        email={account.email}
                        avatarUrl={account.avatar_url}
                      />
                      <div className="account-copy">
                        <h3>{account.display_name}</h3>
                        <p>{account.email}</p>
                        <span>{ruleUsage(account.rule_count)}</span>
                      </div>
                    </div>
                    <div className="account-actions">
                      <Badge variant={connected ? "healthy" : "attention"}>
                        {connected ? (
                          <CheckCircle2 aria-hidden="true" />
                        ) : (
                          <ShieldAlert aria-hidden="true" />
                        )}
                        {connected ? "Connected" : "Disconnected"}
                      </Badge>
                      {connected ? (
                        <>
                          <Button
                            className="account-action"
                            variant="outline"
                            onClick={() => checkAccess(account.id)}
                            disabled={disconnect.isPending || permanentDelete.isPending || verifyAccess.isPending}
                          >
                            <ShieldCheck aria-hidden="true" />
                            {checking ? "Checking access…" : "Check access"}
                          </Button>
                          <Button
                            className="account-action"
                            variant="ghost"
                            onClick={() => confirmDisconnect(account.id)}
                            disabled={disconnect.isPending || permanentDelete.isPending || verifyAccess.isPending}
                            aria-expanded={confirming}
                            aria-controls={confirming ? `disconnect-${account.id}` : undefined}
                          >
                            <Unplug aria-hidden="true" /> Disconnect account
                          </Button>
                        </>
                      ) : (
                        <>
                          {googleConfigured && (
                            <Button className="account-action" variant="outline" asChild>
                              <a href="/api/v1/oauth/google/start" onClick={() => recordAuthorizationStart()}>
                                <KeyRound aria-hidden="true" /> Reauthorize account
                              </a>
                            </Button>
                          )}
                          <Button
                            className="account-action account-delete-action"
                            variant="ghost"
                            onClick={() => confirmPermanentDelete(account.id)}
                            disabled={disconnect.isPending || permanentDelete.isPending}
                            aria-expanded={deleting}
                            aria-controls={deleting ? `delete-${account.id}` : undefined}
                          >
                            <Trash2 aria-hidden="true" /> Delete account
                          </Button>
                        </>
                      )}
                    </div>
                  </div>
                  {access && (
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
                  )}
                  {verifyAccess.error && verifyAccess.variables === account.id && (
                    <div className="inline-error account-access-error" role="alert">
                      {verifyAccess.error.message}
                    </div>
                  )}
                  {confirming && (
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
                          onClick={() => setConfirmingAccountId(null)}
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
                  )}
                  {deleting && (
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
                          onClick={() => setDeletingAccountId(null)}
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
                  )}
                </li>
              )
            })}
                  </ul>
                )}
              </>
            )}
            <GoogleReturnNote help={returnHelp} className="account-group-footer" />
          </div>
        )}
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
      </section>

      <StorageSection />

      <section className="settings-section" aria-labelledby="appearance-title">
        <div className="section-heading">
          <div>
            <h2 id="appearance-title">Appearance</h2>
            <p>Saved in this browser only.</p>
          </div>
        </div>
        <div className="settings-list">
          <div className="setting-row">
            <div>
              <h3 id="theme-title">Theme</h3>
              <p>Follow this device, or keep the interface light or dark.</p>
            </div>
            <div className="appearance-control">
              <NativeSelect
                id="theme-preference"
                aria-labelledby="theme-title"
                value={preference}
                onChange={(event) => setPreference(event.target.value as ThemePreference)}
              >
                <option value="system">Device setting</option>
                <option value="light">Light</option>
                <option value="dark">Dark</option>
              </NativeSelect>
            </div>
          </div>
          <div className="setting-row">
            <div>
              <h3 id="dark-palette-title">Dark palette</h3>
              <p>The colors used whenever the interface is dark.</p>
            </div>
            <div className="appearance-control">
              <NativeSelect
                id="dark-palette"
                aria-labelledby="dark-palette-title"
                value={darkPalette}
                onChange={(event) => setDarkPalette(event.target.value as DarkPalette)}
              >
                <option value="twilight">Twilight (indigo)</option>
                <option value="midnight">Midnight (blue)</option>
              </NativeSelect>
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}

function StorageSection() {
  const queryClient = useQueryClient()
  const storage = useQuery({ queryKey: ["storage"], queryFn: api.storage })
  const [days, setDays] = useState(90)
  const [confirming, setConfirming] = useState<"activity" | "logs" | null>(null)
  const [message, setMessage] = useState("")
  const clearTrigger = useRef<HTMLButtonElement>(null)
  const purgeTrigger = useRef<HTMLButtonElement>(null)
  const clearable = useQuery({
    queryKey: ["storage", "clearable", days],
    queryFn: () => api.clearableActivity(days),
    enabled: confirming === "activity",
  })
  const clear = useMutation({
    mutationFn: () => api.clearActivity(days),
    onSuccess: async (cleared) => {
      setConfirming(null)
      setMessage(
        clearedActivityMessage(cleared.removed, storage.data?.database.reclaimable_bytes ?? 0),
      )
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["storage"] }),
        queryClient.invalidateQueries({ queryKey: ["activity"] }),
      ])
    },
    onError: async (error) => {
      // A 409 means the clear deleted entries but could not reclaim the space while a rule
      // was synchronizing. Close the confirmation, keep the server's message in the alert, and
      // refresh the usage, so the row offers to reclaim the space that is left.
      if (error instanceof ApiError && error.status === 409) {
        setConfirming(null)
        await queryClient.invalidateQueries({ queryKey: ["storage"] })
      }
    },
  })
  const purge = useMutation({
    mutationFn: api.purgeLogs,
    onSuccess: async () => {
      setConfirming(null)
      setMessage("The logs were purged.")
      await queryClient.invalidateQueries({ queryKey: ["storage"] })
    },
  })
  const busy = clear.isPending || purge.isPending
  const usage = storage.data
  const confirmation = clearable.data
    ? clearActivityConfirmation(
        clearable.data.entries,
        days,
        usage?.database.reclaimable_bytes ?? 0,
      )
    : clearable.error
      ? countFailedConfirmation(clearable.error.message)
      : null

  return (
    <section className="settings-section" aria-labelledby="storage-title">
      <div className="section-heading">
        <div>
          <h2 id="storage-title">Storage</h2>
          <p>Activity history and log files kept on this installation.</p>
        </div>
      </div>
      {storage.isPending && <Skeleton className="h-24 w-full" />}
      {storage.error && (
        <div className="inline-error" role="alert">
          Storage usage could not load.
        </div>
      )}
      {usage && (
        <div className="settings-list">
          <div className="setting-row">
            <div>
              <h3>Database</h3>
              <p>{activitySummary(usage.database)}</p>
            </div>
            <div className="storage-actions">
              <div className="storage-select">
                <NativeSelect
                  id="activity-age"
                  aria-label="Clear Activity older than"
                  value={days}
                  disabled={busy}
                  onChange={(event) => setDays(Number(event.target.value))}
                >
                  {usage.activity_ages.map((age) => (
                    <option key={age} value={age}>
                      Older than {age} days
                    </option>
                  ))}
                </NativeSelect>
              </div>
              <Button
                ref={clearTrigger}
                type="button"
                variant="outline"
                disabled={busy || !canClearActivity(usage.database)}
                aria-expanded={confirming === "activity"}
                aria-controls="clear-activity-confirmation"
                onClick={() => {
                  clear.reset()
                  setMessage("")
                  setConfirming("activity")
                }}
              >
                Clear Activity
              </Button>
            </div>
          </div>
          {confirming === "activity" && (
            <DestructiveConfirmation
              id="clear-activity-confirmation"
              title={`Clear Activity older than ${days} days?`}
              body={confirmation?.body ?? "Counting the entries that would be removed…"}
              cancelLabel="Keep Activity"
              confirmLabel={confirmation?.confirmLabel ?? "Clear Activity"}
              pendingLabel={confirmation?.pendingLabel ?? "Clearing…"}
              pending={clear.isPending || clearable.isRefetching}
              confirmDisabled={!confirmation?.canConfirm}
              onConfirm={() => (clearable.error ? void clearable.refetch() : clear.mutate())}
              onCancel={() => {
                setConfirming(null)
                clearTrigger.current?.focus()
              }}
            />
          )}
          <div className="setting-row">
            <div>
              <h3>Logs</h3>
              <p>{logSummary(usage.logs)}</p>
              {!usage.logs && (
                <details className="inline-help setting-help">
                  <summary>
                    <span>How to turn it on</span>
                    <ChevronDown className="inline-help-chevron" aria-hidden="true" />
                  </summary>
                  <div className="inline-help-body">
                    <p>
                      Log files are kept unless <code>CALENDAR_SYNC_LOG_DIR</code> is set to an empty
                      value. Set it to a writable directory, such as <code>/data/logs</code> on the data
                      volume, or remove it from <code>.env</code>, then restart the service.
                    </p>
                    <p>
                      If it already names a directory, that directory could not be used:{" "}
                      <code>docker compose logs app</code> shows the warning that says why.
                    </p>
                  </div>
                </details>
              )}
            </div>
            {usage.logs && (
              <div className="storage-actions">
                <Button variant="outline" asChild>
                  <a href={STORAGE_LOGS_URL} download>
                    <Download aria-hidden="true" /> Download
                  </a>
                </Button>
                <Button
                  ref={purgeTrigger}
                  type="button"
                  variant="outline"
                  disabled={busy || usage.logs.files === 0}
                  aria-expanded={confirming === "logs"}
                  aria-controls="purge-logs-confirmation"
                  onClick={() => {
                    purge.reset()
                    setMessage("")
                    setConfirming("logs")
                  }}
                >
                  Purge logs
                </Button>
              </div>
            )}
          </div>
          {confirming === "logs" && (
            <DestructiveConfirmation
              id="purge-logs-confirmation"
              title="Purge the logs?"
              body="Every log line kept on this installation is deleted. Download them first if you may need them. This cannot be undone."
              cancelLabel="Keep logs"
              confirmLabel="Purge logs"
              pendingLabel="Purging…"
              pending={purge.isPending}
              onConfirm={() => purge.mutate()}
              onCancel={() => {
                setConfirming(null)
                purgeTrigger.current?.focus()
              }}
            />
          )}
        </div>
      )}
      {message && <p role="status">{message}</p>}
      {(clear.error ?? purge.error) && (
        <div className="inline-error" role="alert">
          {(clear.error ?? purge.error)?.message}
        </div>
      )}
    </section>
  )
}
