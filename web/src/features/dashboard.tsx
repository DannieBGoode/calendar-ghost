import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  CircleUserRound,
  CircleDot,
  ExternalLink,
  KeyRound,
  Link2,
  Plus,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Trash2,
  Unplug,
} from "lucide-react"
import { useState, type FormEvent } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { NativeSelect } from "@/components/ui/native-select"
import { Skeleton } from "@/components/ui/skeleton"
import { useTheme } from "@/components/theme-provider"
import { api, type ConnectedAccount } from "@/lib/api"
import { accountInitials } from "@/lib/account-avatar"
import {
  activityFailure,
  activityFailureActions,
  activityFailureMessages,
  activityFailureRequiresReload,
} from "@/lib/activity-failure"
import { oauthRedirectMismatch } from "@/lib/oauth-redirect"
import type { AppView } from "@/lib/navigation"
import type { ThemePreference } from "@/lib/theme"

export function Dashboard({ view, onViewChange }: { view: AppView; onViewChange: (view: AppView) => void }) {
  const dashboard = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard })
  const rules = useQuery({ queryKey: ["rules"], queryFn: api.rules })
  const google = useQuery({
    queryKey: ["google-configuration"],
    queryFn: api.googleConfiguration,
  })

  if (dashboard.isPending || rules.isPending || google.isPending) return <DashboardSkeleton />
  if (dashboard.error || rules.error || google.error) {
    return (
      <section className="page-section" role="alert">
        <h1>Calendar Sync could not load</h1>
        <p className="page-intro">Check that the local service is running, then reload this page.</p>
        <Button onClick={() => window.location.reload()}><RefreshCw /> Reload page</Button>
      </section>
    )
  }

  if (view === "rules") return <RulesView rules={rules.data} dashboard={dashboard.data} onViewChange={onViewChange} />
  if (view === "activity") return <ActivityView />
  if (view === "settings") {
    return (
      <SettingsView
        googleConfigured={google.data.configured}
        redirectUri={google.data.redirect_uri}
      />
    )
  }

  const empty = dashboard.data.connected_accounts === 0
  return (
    <div className="page-section">
      <div className="page-heading-row">
        <div>
          <p className="page-context">Overview</p>
          <h1>{empty ? "Set up your first synchronization" : "Synchronization is healthy"}</h1>
          <p className="page-intro">
            {empty
              ? "Connect a Google identity, choose two calendars, then preview exactly what the rule will create."
              : "Calendar Sync is checking for changes every five minutes."}
          </p>
        </div>
        {!empty && <Button onClick={() => onViewChange("rules")}><RefreshCw /> Review and sync</Button>}
      </div>

      <section className="health-strip" aria-label="Installation health">
        <div className="health-signal">{dashboard.data.health === "healthy" ? <CheckCircle2 aria-hidden="true" /> : <ShieldAlert aria-hidden="true" />}</div>
        <div className="health-copy">
          <div className="health-title-row">
            <h2>{empty ? "Ready for setup" : dashboard.data.health === "healthy" ? "Everything is quiet" : "An incident needs attention"}</h2>
            <Badge variant={dashboard.data.health === "healthy" ? "healthy" : "attention"}><CircleDot aria-hidden="true" /> {dashboard.data.health === "healthy" ? "Healthy" : "Attention"}</Badge>
          </div>
          <p>{empty ? "The service is running and waiting for a connected account." : dashboard.data.health === "healthy" ? "No incidents need your attention." : `${dashboard.data.open_incidents} open incident${dashboard.data.open_incidents === 1 ? "" : "s"}. Open Activity for details.`}</p>
        </div>
        <dl className="health-facts">
          <div><dt>Accounts</dt><dd>{dashboard.data.connected_accounts}</dd></div>
          <div><dt>Rules</dt><dd>{dashboard.data.sync_rules}</dd></div>
          <div><dt>Incidents</dt><dd>{dashboard.data.open_incidents}</dd></div>
        </dl>
      </section>

      {empty ? (
        <OnboardingSteps
          onViewChange={onViewChange}
          googleConfigured={google.data.configured}
          redirectUri={google.data.redirect_uri}
        />
      ) : (
        <RecentRules onViewChange={onViewChange} count={rules.data.length} />
      )}
    </div>
  )
}

function OnboardingSteps({
  onViewChange,
  googleConfigured,
  redirectUri,
}: {
  onViewChange: (view: AppView) => void
  googleConfigured: boolean
  redirectUri: string | null
}) {
  return (
    <section className="workflow" aria-labelledby="workflow-title">
      <div className="section-heading">
        <div><h2 id="workflow-title">Start with an account</h2><p>Nothing is written to Google until a rule passes preview and you enable it.</p></div>
        <span className="step-progress">Step 1 of 3</span>
      </div>
      <RedirectMismatchNotice redirectUri={redirectUri} />
      <ol className="step-list">
        <li className="step-row current">
          <span className="step-number">1</span>
          <div className="step-content">
            <div><h3>Connect a Google identity</h3><p>Authorize calendar discovery and event access for one Google account.</p></div>
            <div className="step-action">
              <Button
                disabled={!googleConfigured}
                onClick={() => window.location.assign("/api/v1/oauth/google/start")}
              >
                <KeyRound /> Connect Google account <ExternalLink />
              </Button>
              {!googleConfigured && (
                <p className="configuration-note" role="status">
                  Add the master key and Google OAuth credentials in <code>.env</code>, then
                  restart.
                </p>
              )}
            </div>
          </div>
        </li>
        <li className="step-row pending">
          <span className="step-number">2</span>
          <div className="step-content"><div><h3>Create a directional rule</h3><p>Choose one source calendar, one destination calendar, and a privacy policy.</p></div></div>
        </li>
        <li className="step-row pending">
          <span className="step-number">3</span>
          <div className="step-content"><div><h3>Preview and enable</h3><p>Review eligible events and destination projections before the first write.</p></div></div>
        </li>
      </ol>
      <Button variant="ghost" onClick={() => onViewChange("rules")}>Learn how rules work <ArrowRight /></Button>
    </section>
  )
}

function RedirectMismatchNotice({ redirectUri }: { redirectUri: string | null }) {
  const mismatch = oauthRedirectMismatch(redirectUri, window.location.origin)
  if (!mismatch) return null
  return (
    <div className="oauth-feedback oauth-feedback-warning" role="status">
      <ShieldAlert aria-hidden="true" />
      <div>
        <h2>Google will return to a different address</h2>
        <p>
          After you approve access, Google sends your browser to <code>{mismatch.redirectOrigin}</code>,
          not <code>{mismatch.currentOrigin}</code>. If that address does not reach this
          installation, the account will not connect.
        </p>
        <p>
          Open Calendar Sync at <code>{mismatch.redirectOrigin}</code>, for example through an SSH
          tunnel, or set <code>CALENDAR_SYNC_GOOGLE_REDIRECT_URI</code> to an HTTPS address for this
          installation. If Google lands on a connection error, replace{" "}
          <code>{mismatch.redirectOrigin}</code> with <code>{mismatch.currentOrigin}</code> in the
          address bar within 10 minutes.
        </p>
      </div>
    </div>
  )
}

function RecentRules({ onViewChange, count }: { onViewChange: (view: AppView) => void; count: number }) {
  return (
    <section className="workflow">
      <div className="section-heading">
        <div><h2>Directional rules</h2><p>{count} configured relationship{count === 1 ? "" : "s"}.</p></div>
        <Button onClick={() => onViewChange("rules")}><Link2 /> View rules</Button>
      </div>
    </section>
  )
}

function RulesView({
  rules,
  dashboard,
  onViewChange,
}: {
  rules: Awaited<ReturnType<typeof api.rules>>
  dashboard: Awaited<ReturnType<typeof api.dashboard>>
  onViewChange: (view: AppView) => void
}) {
  const queryClient = useQueryClient()
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: api.accounts })
  const [showBuilder, setShowBuilder] = useState(false)
  const [previews, setPreviews] = useState<Record<string, Awaited<ReturnType<typeof api.previewRule>>>>({})
  const preview = useMutation({
    mutationFn: api.previewRule,
    onSuccess: async (result) => {
      setPreviews((current) => ({ ...current, [result.rule_id]: result }))
      await queryClient.invalidateQueries({ queryKey: ["rules"] })
    },
  })
  const enable = useMutation({
    mutationFn: api.enableRule,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["rules"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
      ])
    },
  })
  const sync = useMutation({
    mutationFn: api.syncRule,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["activity"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
      ])
    },
  })
  const pause = useMutation({
    mutationFn: api.pauseRule,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["rules"] })
    },
  })
  const reconcile = useMutation({
    mutationFn: api.reconcileRule,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["activity"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
      ])
    },
  })
  const accountsById = new Map(
    (accounts.data ?? []).map((account) => [account.id, account]),
  )

  if (accounts.isPending) return <DashboardSkeleton />
  if (accounts.error) {
    return (
      <section className="page-section" role="alert">
        <h1>Rules could not load account identities</h1>
        <p className="page-intro">Reload the connected accounts before managing rules.</p>
        <Button variant="outline" onClick={() => accounts.refetch()}>
          <RefreshCw aria-hidden="true" /> Try again
        </Button>
      </section>
    )
  }

  return (
    <div className="page-section">
      <div className="page-heading-row">
        <div>
          <p className="page-context">Rules</p>
          <h1>Directional sync rules</h1>
          <p className="page-intro">
            Each rule observes one source calendar and manages projections in one destination
            calendar.
          </p>
        </div>
        <Button
          disabled={dashboard.connected_accounts === 0}
          onClick={() => setShowBuilder((visible) => !visible)}
        >
          <Plus /> {showBuilder ? "Close rule builder" : "Create sync rule"}
        </Button>
      </div>
      {showBuilder && <RuleBuilder onCreated={() => setShowBuilder(false)} />}
      {rules.length === 0 ? (
        <section className="empty-panel">
          <div className="empty-icon"><Link2 /></div>
          <h2>No rules yet</h2>
          <p>{dashboard.connected_accounts === 0 ? "Connect a Google account before creating your first rule." : "Create a rule, preview its effects, then enable it."}</p>
          <Button
            disabled={dashboard.connected_accounts === 0}
            onClick={() => setShowBuilder(true)}
          >
            <Plus /> Create sync rule
          </Button>
        </section>
      ) : (
        <div className="rule-list">
          {rules.map((rule) => {
            const latestPreview = previews[rule.id]
            const sourceAccount = accountsById.get(rule.source.connected_account_id)
            const destinationAccount = accountsById.get(rule.destination.connected_account_id)
            const disconnectedAccounts = [sourceAccount, destinationAccount].filter(
              (account, index, all): account is ConnectedAccount =>
                account?.state === "disconnected" &&
                all.findIndex((candidate) => candidate?.id === account.id) === index,
            )
            const synchronizationStopped =
              rule.state === "degraded" || disconnectedAccounts.length > 0
            return (
              <div className="rule-row" key={rule.id}>
                <div className="rule-details">
                  <div className="rule-direction">
                    <RuleEndpoint
                      account={sourceAccount}
                      accountId={rule.source.connected_account_id}
                      calendarId={rule.source.calendar_id}
                    />
                    <ArrowRight aria-hidden="true" />
                    <RuleEndpoint
                      account={destinationAccount}
                      accountId={rule.destination.connected_account_id}
                      calendarId={rule.destination.calendar_id}
                    />
                  </div>
                  <p className="rule-policy">
                    {rule.privacy_policy === "busy_only" ? "Busy only" : "Copy details"}
                    {rule.sync_all_day_events ? ", including all-day events" : ", timed events only"}
                  </p>
                  {synchronizationStopped && (
                    <div className="rule-recovery-note" role="status">
                      <ShieldAlert aria-hidden="true" />
                      <p>
                        <strong>Synchronization stopped.</strong>{" "}
                        {disconnectedAccounts.length > 0
                          ? `${disconnectedAccounts.map((account) => account.email).join(" and ")} must be reauthorized before this rule can run.`
                          : "This rule is degraded and requires recovery before it can run."}
                      </p>
                    </div>
                  )}
                  {latestPreview && (
                    <p className="preview-result" role="status">
                      Preview found {latestPreview.eligible_events} eligible and {latestPreview.excluded_events} excluded events.
                    </p>
                  )}
                </div>
                <div className="rule-actions">
                  <Badge variant={rule.state === "enabled" ? "healthy" : synchronizationStopped ? "attention" : "neutral"}>
                    {synchronizationStopped ? "Stopped" : rule.state.replaceAll("_", " ")}
                  </Badge>
                  {disconnectedAccounts.length > 0 && synchronizationStopped ? (
                    <Button variant="outline" onClick={() => onViewChange("settings")}>
                      Reauthorize in Settings
                    </Button>
                  ) : ["draft", "paused", "degraded"].includes(rule.state) && (
                    <Button variant="outline" onClick={() => preview.mutate(rule.id)} disabled={preview.isPending}>
                      {preview.isPending ? "Previewing…" : rule.state === "degraded" ? "Validate recovery" : "Preview rule"}
                    </Button>
                  )}
                  {rule.state === "dry_run_validated" && (
                    <Button onClick={() => enable.mutate(rule.id)} disabled={enable.isPending}>
                      Enable rule
                    </Button>
                  )}
                  {rule.state === "enabled" && (
                    <>
                      <Button variant="outline" onClick={() => sync.mutate(rule.id)} disabled={sync.isPending || reconcile.isPending}>
                        <RefreshCw /> {sync.isPending ? "Syncing…" : "Sync now"}
                      </Button>
                      <Button variant="ghost" onClick={() => reconcile.mutate(rule.id)} disabled={sync.isPending || reconcile.isPending}>
                        {reconcile.isPending ? "Reconciling…" : "Reconcile now"}
                      </Button>
                      <Button variant="ghost" onClick={() => pause.mutate(rule.id)} disabled={sync.isPending || reconcile.isPending || pause.isPending}>
                        {pause.isPending ? "Pausing…" : "Pause"}
                      </Button>
                    </>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
      {(preview.error || enable.error || sync.error || reconcile.error || pause.error) && (
        <div className="inline-error" role="alert">{(preview.error ?? enable.error ?? sync.error ?? reconcile.error ?? pause.error)?.message}</div>
      )}
    </div>
  )
}

function RuleEndpoint({
  account,
  accountId,
  calendarId,
}: {
  account: ConnectedAccount | undefined
  accountId: string
  calendarId: string
}) {
  return (
    <span className="rule-endpoint" title={account?.email ?? accountId}>
      <span className="account-mark account-mark-compact" aria-hidden="true">
        {accountInitials(account?.display_name ?? "", account?.email ?? accountId)}
      </span>
      <span>{calendarId}</span>
    </span>
  )
}

function RuleBuilder({ onCreated }: { onCreated: () => void }) {
  const queryClient = useQueryClient()
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: api.accounts })
  const [sourceAccount, setSourceAccount] = useState("")
  const [destinationAccount, setDestinationAccount] = useState("")
  const [sourceCalendar, setSourceCalendar] = useState("")
  const [destinationCalendar, setDestinationCalendar] = useState("")
  const [privacy, setPrivacy] = useState<"busy_only" | "copy_details">("busy_only")
  const [allDay, setAllDay] = useState(true)

  const connectedAccounts = accounts.data?.filter((account) => account.state === "connected")
  const resolvedSourceAccount = sourceAccount || connectedAccounts?.[0]?.id || ""
  const resolvedDestinationAccount = destinationAccount || connectedAccounts?.[0]?.id || ""

  const sourceCalendars = useQuery({
    queryKey: ["calendars", resolvedSourceAccount],
    queryFn: () => api.calendars(resolvedSourceAccount),
    enabled: Boolean(resolvedSourceAccount),
  })
  const destinationCalendars = useQuery({
    queryKey: ["calendars", resolvedDestinationAccount],
    queryFn: () => api.calendars(resolvedDestinationAccount),
    enabled: Boolean(resolvedDestinationAccount),
  })

  const resolvedSourceCalendar = sourceCalendar || sourceCalendars.data?.[0]?.id || ""
  const writableDestination = destinationCalendars.data?.find((calendar) =>
    ["writer", "owner"].includes(calendar.access_role),
  )
  const resolvedDestinationCalendar = destinationCalendar || writableDestination?.id || ""

  const create = useMutation({
    mutationFn: () =>
      api.createRule({
        source: {
          connected_account_id: resolvedSourceAccount,
          calendar_id: resolvedSourceCalendar,
        },
        destination: {
          connected_account_id: resolvedDestinationAccount,
          calendar_id: resolvedDestinationCalendar,
        },
        privacy_policy: privacy,
        sync_all_day_events: allDay,
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["rules"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
      ])
      onCreated()
    },
  })

  const sameEndpoint =
    resolvedSourceAccount === resolvedDestinationAccount &&
    resolvedSourceCalendar === resolvedDestinationCalendar
  const canSubmit = Boolean(
    resolvedSourceAccount &&
      resolvedDestinationAccount &&
      resolvedSourceCalendar &&
      resolvedDestinationCalendar &&
      !sameEndpoint,
  )

  function submit(event: FormEvent) {
    event.preventDefault()
    if (canSubmit) create.mutate()
  }

  return (
    <section className="rule-builder" aria-labelledby="builder-title">
      <div className="section-heading">
        <div>
          <h2 id="builder-title">Choose the relationship</h2>
          <p>Save a draft first. Preview is required before the rule can be enabled.</p>
        </div>
      </div>
      <form className="rule-form" onSubmit={submit}>
        <fieldset>
          <legend>Source calendar</legend>
          <div className="field-stack">
            <Label htmlFor="source-account">Google identity</Label>
            <NativeSelect id="source-account" value={resolvedSourceAccount} onChange={(event) => { setSourceAccount(event.target.value); setSourceCalendar("") }}>
              {connectedAccounts?.map((account) => <option key={account.id} value={account.id}>{account.display_name} ({account.email})</option>)}
            </NativeSelect>
          </div>
          <div className="field-stack">
            <Label htmlFor="source-calendar">Calendar</Label>
            <NativeSelect id="source-calendar" value={resolvedSourceCalendar} onChange={(event) => setSourceCalendar(event.target.value)}>
              {sourceCalendars.data?.map((calendar) => <option key={calendar.id} value={calendar.id}>{calendar.summary}</option>)}
            </NativeSelect>
          </div>
        </fieldset>
        <div className="direction-marker" aria-hidden="true"><ArrowRight /></div>
        <fieldset>
          <legend>Destination calendar</legend>
          <div className="field-stack">
            <Label htmlFor="destination-account">Google identity</Label>
            <NativeSelect id="destination-account" value={resolvedDestinationAccount} onChange={(event) => { setDestinationAccount(event.target.value); setDestinationCalendar("") }}>
              {connectedAccounts?.map((account) => <option key={account.id} value={account.id}>{account.display_name} ({account.email})</option>)}
            </NativeSelect>
          </div>
          <div className="field-stack">
            <Label htmlFor="destination-calendar">Writable calendar</Label>
            <NativeSelect id="destination-calendar" value={resolvedDestinationCalendar} onChange={(event) => setDestinationCalendar(event.target.value)}>
              {destinationCalendars.data?.filter((calendar) => ["writer", "owner"].includes(calendar.access_role)).map((calendar) => <option key={calendar.id} value={calendar.id}>{calendar.summary}</option>)}
            </NativeSelect>
          </div>
        </fieldset>
        <fieldset className="policy-fields">
          <legend>Projection policy</legend>
          <div className="field-stack">
            <Label htmlFor="privacy-policy">Event information</Label>
            <NativeSelect id="privacy-policy" value={privacy} onChange={(event) => setPrivacy(event.target.value as "busy_only" | "copy_details")}>
              <option value="busy_only">Busy only (recommended)</option>
              <option value="copy_details">Copy title, description, and location</option>
            </NativeSelect>
          </div>
          <label className="checkbox-row"><input type="checkbox" checked={allDay} onChange={(event) => setAllDay(event.target.checked)} /><span><strong>Sync all-day events</strong><small>Turn this off to synchronize timed events only.</small></span></label>
        </fieldset>
        {sameEndpoint && <p className="field-error" role="alert">Choose a different destination calendar.</p>}
        {create.error && <div className="inline-error" role="alert">{create.error.message}</div>}
        <div className="form-actions"><Button type="submit" disabled={!canSubmit || create.isPending}>{create.isPending ? "Saving draft…" : "Save rule draft"}</Button></div>
      </form>
    </section>
  )
}

function ActivityView() {
  const activity = useQuery({ queryKey: ["activity"], queryFn: api.activity })
  const incidents = useQuery({ queryKey: ["incidents"], queryFn: api.incidents })
  if (activity.isPending || incidents.isPending) return <DashboardSkeleton />

  if (activity.error || incidents.error) {
    const failure = activityFailure([activity.error, incidents.error])
    const reloadRequired = activityFailureRequiresReload(failure)
    const refreshing = activity.isFetching || incidents.isFetching
    const recover = () => {
      if (reloadRequired) {
        window.location.reload()
        return
      }
      void Promise.all([activity.refetch(), incidents.refetch()])
    }

    return (
      <div className="page-section">
        <ActivityHeading />
        <section className="empty-panel" role="alert" aria-labelledby="activity-error-title">
          <div className="empty-icon empty-icon-error"><ShieldAlert aria-hidden="true" /></div>
          <h2 id="activity-error-title">Activity is temporarily unavailable</h2>
          <p>{activityFailureMessages[failure]}</p>
          <Button variant="outline" onClick={recover} disabled={refreshing}>
            <RefreshCw aria-hidden="true" />
            {refreshing && !reloadRequired ? "Trying again…" : activityFailureActions[failure]}
          </Button>
        </section>
      </div>
    )
  }

  return <div className="page-section"><ActivityHeading />
    {incidents.data.length > 0 && <section className="workflow"><div className="section-heading"><div><h2>Incidents</h2><p>Authorization and repeated provider failures that may require attention.</p></div></div><div className="rule-list">{incidents.data.map((incident) => <div className="rule-row" key={incident.id}><div><strong>{incident.summary}</strong><p className="rule-policy">Rule {incident.rule_id ?? "installation"} · Updated {new Date(incident.updated_at).toLocaleString()}</p></div><Badge variant={incident.state === "open" ? "attention" : "neutral"}>{incident.state}</Badge></div>)}</div></section>}
    {activity.data.length === 0 ? <section className="empty-panel"><div className="empty-icon"><Activity aria-hidden="true" /></div><h2>No activity yet</h2><p>Synchronization decisions will appear here after an enabled rule completes its first run.</p></section> : <section className="workflow"><div className="section-heading"><div><h2>Latest actions</h2><p>The 100 most recent synchronization decisions.</p></div></div><div className="rule-list">{activity.data.map((entry, index) => <div className="rule-row" key={`${entry.occurred_at}-${entry.rule_id}-${index}`}><div><strong>{entry.action.replaceAll("_", " ")}</strong><p className="rule-policy">{entry.detail} · {new Date(entry.occurred_at).toLocaleString()}</p></div><Badge variant={entry.outcome === "completed" ? "healthy" : "attention"}>{entry.outcome}</Badge></div>)}</div></section>}
  </div>
}

function ActivityHeading() {
  return (
    <div>
      <p className="page-context">Activity</p>
      <h1>Incidents and audit activity</h1>
      <p className="page-intro">
        Operational details appear here without retaining event titles or descriptions.
      </p>
    </div>
  )
}

function SettingsView({
  googleConfigured,
  redirectUri,
}: {
  googleConfigured: boolean
  redirectUri: string | null
}) {
  const { preference, setPreference } = useTheme()
  const queryClient = useQueryClient()
  const oauthOutcome = new URLSearchParams(window.location.search).get("google")
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
    <div className="page-section">
      <div>
        <p className="page-context">Settings</p>
        <h1>Installation settings</h1>
        <p className="page-intro">
          Manage Google identities and operational defaults for this installation.
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
              <a href="/api/v1/oauth/google/start">Try again</a>
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
              <a href="/api/v1/oauth/google/start">Try again</a>
            </Button>
          )}
        </div>
      )}

      <section className="settings-section" aria-labelledby="accounts-title">
        <div className="section-heading">
          <div>
            <h2 id="accounts-title">Connected accounts</h2>
            <p>Choose which Google identities this installation can use for calendar rules.</p>
          </div>
          {googleConfigured ? (
            <Button asChild>
              <a href="/api/v1/oauth/google/start">
                <Plus aria-hidden="true" /> Connect Google account
              </a>
            </Button>
          ) : (
            <Badge variant="attention"><ShieldAlert aria-hidden="true" /> Not configured</Badge>
          )}
        </div>

        {!googleConfigured && (
          <div className="inline-error" role="status">
            Add the master key and Google OAuth credentials in <code>.env</code>, then restart
            before connecting an account.
          </div>
        )}
        <RedirectMismatchNotice redirectUri={redirectUri} />
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
        {accounts.data?.length === 0 && (
          <div className="account-empty">
            <CircleUserRound aria-hidden="true" />
            <div>
              <h3>No Google accounts connected</h3>
              <p>Connect an account to discover calendars and create a Directional Sync Rule.</p>
            </div>
          </div>
        )}
        {accounts.data && accounts.data.length > 0 && (
          <ul className="account-list">
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
                      <span className="account-mark" aria-hidden="true">
                        {accountInitials(account.display_name, account.email)}
                      </span>
                      <div className="account-copy">
                        <h3>{account.display_name}</h3>
                        <p>{account.email}</p>
                        <span>
                          {account.rule_count} Directional Sync Rule
                          {account.rule_count === 1 ? "" : "s"}
                        </span>
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
                              <a href="/api/v1/oauth/google/start">
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

      <section className="settings-section" aria-labelledby="appearance-title">
        <div className="settings-list">
          <div className="setting-row">
            <div>
              <h2 id="appearance-title">Appearance</h2>
              <p>Follow this device, or keep the interface light or dark in this browser.</p>
            </div>
            <div className="appearance-control">
              <NativeSelect
                id="theme-preference"
                aria-label="Color theme"
                value={preference}
                onChange={(event) => setPreference(event.target.value as ThemePreference)}
              >
                <option value="system">Device setting</option>
                <option value="light">Light</option>
                <option value="dark">Dark</option>
              </NativeSelect>
            </div>
          </div>
        </div>
      </section>

      <section className="settings-section" aria-labelledby="operations-title">
        <div className="section-heading">
          <div>
            <h2 id="operations-title">Operations</h2>
            <p>Runtime behavior and incident visibility for this installation.</p>
          </div>
        </div>
        <div className="settings-list">
          <div className="setting-row">
            <div>
              <h3>Scheduled sync</h3>
              <p>Check enabled rules for changes every five minutes.</p>
            </div>
            <Badge variant="healthy"><CheckCircle2 aria-hidden="true" /> Active</Badge>
          </div>
          <div className="setting-row">
            <div>
              <h3>Incident notifications</h3>
              <p>
                Incidents always appear in Activity. Optional SMTP and webhook delivery use the
                self-hosted environment.
              </p>
            </div>
            <Button variant="outline" asChild>
              <a href="/api/docs" target="_blank" rel="noreferrer">
                View API docs <ExternalLink aria-hidden="true" />
              </a>
            </Button>
          </div>
        </div>
      </section>
    </div>
  )
}

function DashboardSkeleton() {
  return <div className="page-section" aria-label="Loading overview"><Skeleton className="h-4 w-24" /><Skeleton className="h-10 w-80 max-w-full" /><Skeleton className="h-20 w-full" /><Skeleton className="h-72 w-full" /></div>
}
