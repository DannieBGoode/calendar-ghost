import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowRight, CheckCircle2, Plus, ShieldAlert } from "lucide-react"
import { useEffect, useRef, useState, type FormEvent } from "react"

import { GhostMark } from "@/components/ghost-mark"
import { LoadFailure } from "@/components/load-failure"
import { PageSkeleton } from "@/components/page-skeleton"
import {
  LiveAnnouncement,
  PreviewReadyNote,
  RuleCommandMenu,
  RuleFeedbackNote,
  RuleNextAction,
  RuleStatusBadge,
  RuleWorkNote,
} from "@/components/rule-commands"
import { InvitationResponseFields } from "@/components/invitation-response-fields"
import { RuleEndpoint } from "@/components/rule-endpoint"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { NativeSelect } from "@/components/ui/native-select"
import {
  api,
  type ConnectedAccount,
  type DiscoveredCalendar,
  type Rule,
  type TentativeEvents,
  type UnansweredInvitations,
} from "@/lib/api"
import { appPathForRule, appPathForView, isPlainLeftClick, type OpenRule, type ViewChange } from "@/lib/navigation"
import { useRemovingRuleIds } from "@/lib/rule-removal"
import { lastRunLabel } from "@/lib/rule-run"
import { busyCommand, ruleWork, workRefreshInterval } from "@/lib/rule-work"
import { useNow } from "@/lib/use-now"
import { useRuleCommands } from "@/lib/use-rule-commands"
import { useRuleEndpoints } from "@/lib/use-rule-endpoints"

const WRITABLE_ROLES = ["writer", "owner"]
const CALENDAR_STALE_TIME = 5 * 60 * 1000

export function RulesView({
  notice,
  createRule,
  onViewChange,
  onOpenRule,
}: {
  notice: { text: string; attention: boolean } | null
  createRule: boolean
  onViewChange: ViewChange
  onOpenRule: OpenRule
}) {
  const now = useNow()
  const commands = useRuleCommands()
  const rules = useQuery({
    queryKey: ["rules"],
    queryFn: api.rules,
    refetchInterval: (query) => workRefreshInterval(query.state.data, 60_000, commands.pending),
  })
  const { accounts, endpoints } = useRuleEndpoints(rules.data ?? [])
  const removingIds = useRemovingRuleIds(rules.data)
  const [builderChoice, setBuilderChoice] = useState<boolean | null>(null)
  const [noticeDismissed, setNoticeDismissed] = useState(false)
  const createButton = useRef<HTMLButtonElement>(null)
  const rows = useRef(new Map<string, HTMLLIElement>())

  if (rules.isPending || accounts.isPending) return <PageSkeleton label="Loading rules" />
  if (rules.error || accounts.error) {
    return (
      <LoadFailure
        title="Rules could not load"
        onRetry={() => {
          void rules.refetch()
          void accounts.refetch()
        }}
      />
    )
  }

  const connected = accounts.data.filter((account) => account.state === "connected")
  // Arriving from "Create a rule" opens the builder directly; nothing else opens it unasked.
  const showBuilder = builderChoice ?? (createRule && connected.length > 0)

  return (
    <div className="page-section">
      <LiveAnnouncement text={commands.announcement} />
      <div className="page-heading-row">
        <div>
          <h1>Sync rules</h1>
          <p className="page-intro">
            Each rule shows the events of one calendar in another, as busy time or with their
            details. The source calendar is never changed.
          </p>
        </div>
        <div className="heading-action">
          <Button
            ref={createButton}
            variant={showBuilder ? "outline" : "default"}
            disabled={connected.length === 0}
            onClick={() => setBuilderChoice(!showBuilder)}
            aria-expanded={showBuilder}
            aria-controls="rule-builder"
            aria-describedby={connected.length === 0 ? "create-rule-hint" : undefined}
          >
            {showBuilder ? "Close rule builder" : <><Plus aria-hidden="true" /> Create sync rule</>}
          </Button>
          {connected.length === 0 && (
            <p id="create-rule-hint" className="action-hint">
              <a
                href={appPathForView("settings")}
                onClick={(event) => {
                  if (!isPlainLeftClick(event)) return
                  event.preventDefault()
                  onViewChange("settings")
                }}
              >
                Connect a Google account
              </a>{" "}
              first.
            </p>
          )}
        </div>
      </div>
      {notice && !noticeDismissed && (
        <div className="page-notice" data-tone={notice.attention ? "attention" : undefined}>
          {notice.attention ? <ShieldAlert aria-hidden="true" /> : <CheckCircle2 aria-hidden="true" />}
          <p>{notice.text}</p>
          <div className="page-notice-actions">
            {notice.attention && (
              <Button variant="outline" asChild>
                <a
                  href={appPathForView("activity")}
                  onClick={(event) => {
                    if (!isPlainLeftClick(event)) return
                    event.preventDefault()
                    onViewChange("activity")
                  }}
                >
                  Review in Activity
                </a>
              </Button>
            )}
            <Button variant="ghost" onClick={() => setNoticeDismissed(true)}>Dismiss</Button>
          </div>
        </div>
      )}
      {showBuilder && (
        <RuleBuilder
          accounts={connected}
          onCreated={(rule) => {
            setBuilderChoice(false)
            commands.notify(rule.id, {
              tone: "success",
              text: "Draft saved. Preview it to see exactly what will be written before anything changes.",
            })
            createButton.current?.focus()
          }}
        />
      )}
      {rules.data.length === 0 ? (
        !showBuilder && (
          <section className="empty-note" aria-labelledby="no-rules-title">
            <GhostMark className="empty-ghost" />
            <div>
              <h2 id="no-rules-title">No rules yet</h2>
              <p>
                {connected.length === 0
                  ? "Connect a Google account in Settings, then create your first rule here."
                  : "Create a rule, preview its effects, then start syncing."}
              </p>
            </div>
          </section>
        )
      ) : (
        <ul className="rule-list" aria-label="Sync rules">
          {rules.data.map((rule) => {
            const { source, destination, disconnected } = endpoints(rule)
            const stopped = rule.state === "degraded" || disconnected.length > 0
            const removing = removingIds.has(rule.id)
            const work = ruleWork({
              pending: commands.pending[rule.id],
              pendingSince: commands.pendingSince[rule.id],
              running: rule.running,
              removing,
            })
            const pending = busyCommand(commands.pending[rule.id], work)
            const state = removing ? "removing" : rule.state
            const headingId = `rule-${rule.id}-name`
            const previewId = `rule-${rule.id}-preview`
            const run = (command: Parameters<typeof commands.run>[1]) =>
              void commands.run(rule.id, command, destination.name, () => rows.current.get(rule.id) ?? null)
            return (
              <li
                className="rule-row"
                key={rule.id}
                tabIndex={-1}
                aria-labelledby={headingId}
                aria-busy={work ? true : undefined}
                ref={(element) => {
                  if (element) rows.current.set(rule.id, element)
                  else rows.current.delete(rule.id)
                }}
              >
                <div className="rule-main">
                  <div className="rule-summary">
                    <h2 className="sr-only" id={headingId}>{source.name} to {destination.name}</h2>
                    <div className="rule-direction">
                      <RuleEndpoint
                        account={source.account}
                        endpoint={rule.source}
                        calendars={source.calendars}
                        role="Source"
                      />
                      <ArrowRight aria-hidden="true" />
                      <RuleEndpoint
                        account={destination.account}
                        endpoint={rule.destination}
                        calendars={destination.calendars}
                        role="Destination"
                      />
                    </div>
                    <p className="rule-policy">
                      <span>
                        {rule.privacy_policy === "busy_only" ? "Busy only" : "Copy details"}
                        {rule.sync_all_day_events ? ", including all-day events" : ", timed events only"}
                      </span>
                      <span className="rule-run" data-failed={rule.last_sync?.succeeded === false || undefined}>
                        {rule.last_sync?.succeeded === false && <ShieldAlert aria-hidden="true" />}
                        {lastRunLabel(rule.last_sync, now)}
                      </span>
                    </p>
                  </div>
                  <div className="rule-actions">
                    <RuleStatusBadge state={state} stopped={stopped} working={work?.kind} />
                    <RuleNextAction
                      state={state}
                      disconnected={disconnected.length > 0}
                      pending={pending}
                      describedBy={state === "dry_run_validated" ? `${headingId} ${previewId}` : headingId}
                      onRun={run}
                      onViewChange={onViewChange}
                    />
                    <Button variant="ghost" asChild>
                      <a
                        href={appPathForRule(rule.id)}
                        onClick={(event) => {
                          if (!isPlainLeftClick(event)) return
                          event.preventDefault()
                          onOpenRule(rule.id)
                        }}
                        aria-label={`Details for ${source.name} to ${destination.name}`}
                      >
                        Details <ArrowRight aria-hidden="true" />
                      </a>
                    </Button>
                    <RuleCommandMenu
                      state={state}
                      disconnected={disconnected.length > 0}
                      pending={pending}
                      source={source.name}
                      destination={destination.name}
                      reserveSpace
                      onRun={run}
                    />
                  </div>
                </div>
                {rule.reprojection_required && ["draft", "paused", "degraded"].includes(rule.state) && (
                  <p className="rule-note">
                    Preview required: the policy changed, so existing projections are rewritten on the
                    first run after you start syncing again.
                  </p>
                )}
                {stopped && (
                  <p className="rule-note">
                    {disconnected.length > 0
                      ? `Synchronization stopped: ${disconnected.map((account) => account.email).join(" and ")} must be reauthorized before this rule can run.`
                      : "Synchronization stopped to protect your calendars. Nothing was lost; preview the rule to restart it."}
                  </p>
                )}
                {state === "dry_run_validated" && (
                  <PreviewReadyNote id={previewId} preview={rule.latest_preview} destination={destination.name} />
                )}
                {work ? (
                  <RuleWorkNote work={work} source={source.name} destination={destination.name} />
                ) : (
                  <RuleFeedbackNote feedback={commands.feedback[rule.id]} />
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

function firstOtherCalendar(
  calendars: DiscoveredCalendar[] | undefined,
  exclude: string | null,
): string {
  const writable = (calendars ?? []).filter((calendar) => WRITABLE_ROLES.includes(calendar.access_role))
  return (writable.find((calendar) => calendar.id !== exclude) ?? writable[0])?.id ?? ""
}

function RuleBuilder({
  accounts,
  onCreated,
}: {
  accounts: ConnectedAccount[]
  onCreated: (rule: Rule) => void
}) {
  const queryClient = useQueryClient()
  const heading = useRef<HTMLHeadingElement>(null)
  const [sourceAccount, setSourceAccount] = useState("")
  const [destinationAccount, setDestinationAccount] = useState("")
  const [sourceCalendar, setSourceCalendar] = useState("")
  const [destinationCalendar, setDestinationCalendar] = useState("")
  const [privacy, setPrivacy] = useState<"busy_only" | "copy_details">("busy_only")
  const [allDay, setAllDay] = useState(true)
  const [responses, setResponses] = useState<{
    tentative_events: TentativeEvents
    unanswered_invitations: UnansweredInvitations
  }>({ tentative_events: "mark", unanswered_invitations: "as_tentative" })

  useEffect(() => {
    heading.current?.focus()
  }, [])

  const resolvedSourceAccount = sourceAccount || accounts[0]?.id || ""
  const resolvedDestinationAccount = destinationAccount || accounts[1]?.id || accounts[0]?.id || ""

  const sourceCalendars = useQuery({
    queryKey: ["calendars", resolvedSourceAccount],
    queryFn: () => api.calendars(resolvedSourceAccount),
    enabled: Boolean(resolvedSourceAccount),
    staleTime: CALENDAR_STALE_TIME,
  })
  const destinationCalendars = useQuery({
    queryKey: ["calendars", resolvedDestinationAccount],
    queryFn: () => api.calendars(resolvedDestinationAccount),
    enabled: Boolean(resolvedDestinationAccount),
    staleTime: CALENDAR_STALE_TIME,
  })

  const resolvedSourceCalendar = sourceCalendar || sourceCalendars.data?.[0]?.id || ""
  const writableDestinations = (destinationCalendars.data ?? []).filter((calendar) =>
    WRITABLE_ROLES.includes(calendar.access_role),
  )
  // Default to a destination other than the source so the builder never opens in an error.
  const resolvedDestinationCalendar =
    destinationCalendar ||
    firstOtherCalendar(
      destinationCalendars.data,
      resolvedSourceAccount === resolvedDestinationAccount ? resolvedSourceCalendar : null,
    )

  const create = useMutation({
    mutationFn: () =>
      api.createRule({
        source: { connected_account_id: resolvedSourceAccount, calendar_id: resolvedSourceCalendar },
        destination: { connected_account_id: resolvedDestinationAccount, calendar_id: resolvedDestinationCalendar },
        privacy_policy: privacy,
        sync_all_day_events: allDay,
        ...responses,
      }),
    onSuccess: async (rule) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["rules"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
      ])
      onCreated(rule)
    },
  })

  const sameEndpoint =
    resolvedSourceAccount === resolvedDestinationAccount && resolvedSourceCalendar === resolvedDestinationCalendar
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

  const sourceStatus = calendarStatus(sourceCalendars, sourceCalendars.data?.length ?? 0, "calendars")
  const destinationStatus = calendarStatus(destinationCalendars, writableDestinations.length, "writable calendars")

  return (
    <section className="rule-builder" id="rule-builder" aria-labelledby="builder-title">
      <div className="section-heading">
        <div>
          <h2 id="builder-title" ref={heading} tabIndex={-1}>Choose the calendars</h2>
          <p>Saving creates a draft. Nothing is written until you preview the rule and start syncing.</p>
        </div>
      </div>
      <form className="rule-form" onSubmit={submit}>
        <fieldset>
          <legend>Source calendar</legend>
          <div className="field-stack">
            <Label htmlFor="source-account">Google account</Label>
            <NativeSelect id="source-account" value={resolvedSourceAccount} onChange={(event) => { setSourceAccount(event.target.value); setSourceCalendar("") }}>
              {accounts.map((account) => <option key={account.id} value={account.id}>{account.display_name} ({account.email})</option>)}
            </NativeSelect>
          </div>
          <div className="field-stack">
            <Label htmlFor="source-calendar">Calendar</Label>
            <NativeSelect
              id="source-calendar"
              value={resolvedSourceCalendar}
              onChange={(event) => setSourceCalendar(event.target.value)}
              disabled={!sourceCalendars.data?.length}
              aria-describedby={sourceStatus ? "source-calendar-status" : undefined}
            >
              {sourceCalendars.data?.map((calendar) => <option key={calendar.id} value={calendar.id}>{calendar.summary}</option>)}
            </NativeSelect>
            {sourceStatus && <p id="source-calendar-status" className="field-hint">{sourceStatus}</p>}
          </div>
        </fieldset>
        <div className="direction-marker" aria-hidden="true"><ArrowRight /></div>
        <fieldset>
          <legend>Destination calendar</legend>
          <div className="field-stack">
            <Label htmlFor="destination-account">Google account</Label>
            <NativeSelect id="destination-account" value={resolvedDestinationAccount} onChange={(event) => { setDestinationAccount(event.target.value); setDestinationCalendar("") }}>
              {accounts.map((account) => <option key={account.id} value={account.id}>{account.display_name} ({account.email})</option>)}
            </NativeSelect>
          </div>
          <div className="field-stack">
            <Label htmlFor="destination-calendar">Calendar you can edit</Label>
            <NativeSelect
              id="destination-calendar"
              value={resolvedDestinationCalendar}
              onChange={(event) => setDestinationCalendar(event.target.value)}
              disabled={!writableDestinations.length}
              aria-invalid={sameEndpoint || undefined}
              aria-describedby={
                sameEndpoint ? "destination-calendar-error" : destinationStatus ? "destination-calendar-status" : undefined
              }
            >
              {writableDestinations.map((calendar) => <option key={calendar.id} value={calendar.id}>{calendar.summary}</option>)}
            </NativeSelect>
            {sameEndpoint ? (
              <p id="destination-calendar-error" className="field-error" role="alert">
                Choose a destination different from the source calendar.
              </p>
            ) : (
              destinationStatus && <p id="destination-calendar-status" className="field-hint">{destinationStatus}</p>
            )}
          </div>
        </fieldset>
        <fieldset className="policy-fields">
          <legend>What the destination shows</legend>
          <div className="field-stack">
            <Label htmlFor="privacy-policy">Event information</Label>
            <NativeSelect id="privacy-policy" value={privacy} onChange={(event) => setPrivacy(event.target.value as "busy_only" | "copy_details")}>
              <option value="busy_only">Busy only (recommended)</option>
              <option value="copy_details">Copy title, description, and location</option>
            </NativeSelect>
          </div>
          <label className="checkbox-row"><input type="checkbox" checked={allDay} onChange={(event) => setAllDay(event.target.checked)} /><span><strong>Sync all-day events</strong><small>Turn this off to synchronize timed events only.</small></span></label>
          <InvitationResponseFields
            idPrefix=""
            policy={{ privacy_policy: privacy, ...responses }}
            onChange={setResponses}
          />
        </fieldset>
        {create.error && <div className="inline-error" role="alert">{create.error.message}</div>}
        <div className="form-actions"><Button type="submit" disabled={!canSubmit || create.isPending}>{create.isPending ? "Saving draft…" : "Save rule draft"}</Button></div>
      </form>
    </section>
  )
}

function calendarStatus(
  query: { isPending: boolean; isFetching: boolean; error: Error | null },
  available: number,
  noun: string,
): string | null {
  if (query.error) return `Calendars could not load: ${query.error.message}`
  if (query.isPending && query.isFetching) return "Loading calendars…"
  if (!query.isPending && available === 0) return `This account has no ${noun} to choose.`
  return null
}
