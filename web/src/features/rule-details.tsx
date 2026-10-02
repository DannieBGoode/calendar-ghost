import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, ArrowRight, LoaderCircle, RefreshCw, ShieldAlert, Trash2 } from "lucide-react"
import { useEffect, useRef, useState, type FormEvent, type RefObject } from "react"

import { DestructiveConfirmation } from "@/components/destructive-confirmation"
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
  ApiError,
  api,
  type ConnectedAccount,
  type DiscoveredCalendar,
  type ProjectionHandling,
  type RuleDetail,
  type RulePolicyPayload,
  type RuleSummary,
  type RunOutcome,
} from "@/lib/api"
import {
  activitySearch,
  appPathForView,
  isPlainLeftClick,
  isViewingRule,
  type OpenRule,
  type ViewChange,
} from "@/lib/navigation"
import {
  plural,
  policyChanged,
  policyChangeConsequences,
  removalConfirmLabel,
  removalConsequence,
  removalOutcome,
  removalOutcomeUnknown,
  replacementConfirmLabel,
  type RemovalOutcome,
  runOutcomeSummary,
} from "@/lib/rule-change"
import { tentativeFact, unansweredFact } from "@/lib/invitation-responses"
import { ruleEndpointLabel } from "@/lib/rule-endpoint"
import {
  elapsedLabel,
  removalErrorMessage,
  removalMutationKey,
  removalProgress,
  REMOVAL_REFRESH_MS,
  reportedRemoval,
  useActiveRemoval,
  type ActiveRemoval,
  type RemovalRequest,
} from "@/lib/rule-removal"
import { relativeTime } from "@/lib/relative-time"
import { recoveryExplanation } from "@/lib/rule-run"
import { busyCommand, ruleWork, workRefreshInterval } from "@/lib/rule-work"
import { useNow } from "@/lib/use-now"
import { RULE_CHANGE_QUERIES, useRuleCommands, type RuleFeedback } from "@/lib/use-rule-commands"

const PREVIEWABLE_STATES = ["draft", "paused", "degraded"]

export function RuleDetailsView({
  ruleId,
  notice,
  onViewChange,
  onOpenRule,
}: {
  ruleId: string
  notice: string | null
  onViewChange: ViewChange
  onOpenRule: OpenRule
}) {
  const now = useNow()
  const commands = useRuleCommands()
  const sessionRemoval = useActiveRemoval(ruleId)
  const rule = useQuery({
    queryKey: ["rule", ruleId],
    queryFn: () => api.rule(ruleId),
    retry: false,
    // A removal commits each projection it deletes, so refresh quickly to show its progress.
    refetchInterval: (query) =>
      sessionRemoval ? REMOVAL_REFRESH_MS : workRefreshInterval(query.state.data && [query.state.data], 60_000, commands.pending),
  })
  // A failed refresh keeps stale data, which must not keep a finished removal on screen.
  const reported = rule.error ? undefined : reportedRemoval(rule.data?.running, rule.data?.mapping_count ?? 0)
  const removal = reported ?? sessionRemoval
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: api.accounts })
  const heading = useRef<HTMLHeadingElement>(null)
  const loadedRuleId = rule.data?.id
  const accountIds = rule.data
    ? [...new Set([rule.data.source.connected_account_id, rule.data.destination.connected_account_id])]
    : []
  const connectedIds = accountIds.filter(
    (id) => accounts.data?.find((account) => account.id === id)?.state === "connected",
  )
  const calendarQueries = useQueries({
    queries: connectedIds.map((accountId) => ({
      queryKey: ["calendars", accountId],
      queryFn: () => api.calendars(accountId),
      staleTime: 5 * 60 * 1000,
    })),
  })
  const calendarsByAccount = new Map(
    connectedIds.map((accountId, index) => [accountId, calendarQueries[index]?.data]),
  )

  // Wait for calendar names so the focused heading never announces placeholder names; names
  // recorded when Google last listed the calendars serve until it answers again.
  const namesRecorded = Boolean(rule.data?.source.calendar_name && rule.data.destination.calendar_name)
  const namesReady = namesRecorded || calendarQueries.every((query) => !query.isPending)
  useEffect(() => {
    if (loadedRuleId && namesReady) heading.current?.focus()
  }, [loadedRuleId, namesReady])

  const back = (
    <a
      className="back-link"
      href={appPathForView("rules")}
      onClick={(event) => {
        if (!isPlainLeftClick(event)) return
        event.preventDefault()
        onViewChange("rules")
      }}
    >
      <ArrowLeft aria-hidden="true" /> All rules
    </a>
  )

  if (rule.isPending || accounts.isPending) return <PageSkeleton label="Loading rule" />
  // The last refresh of a finishing removal can find the rule gone before the removal returns.
  if (!rule.data || (rule.error && !sessionRemoval) || accounts.error) {
    const missing = rule.error instanceof ApiError && rule.error.status === 404
    // Stale data still describes the removal this page was showing when the rule disappeared.
    const removed = missing && rule.data?.running?.kind === "removal"
    return (
      <section className="page-section" role="alert">
        {back}
        <h1>{removed ? "Rule removed" : missing ? "This rule no longer exists" : "Rule details could not load"}</h1>
        <p className="page-intro">
          {removed
            ? "Its removal finished. Activity lists what happened to each of its events."
            : missing
              ? "It may have been removed or replaced. Return to the rules list to continue."
              : "Check that the local service is running, then try again."}
        </p>
        {!missing && (
          <Button
            variant="outline"
            onClick={() => {
              void rule.refetch()
              void accounts.refetch()
            }}
          >
            <RefreshCw aria-hidden="true" /> Try again
          </Button>
        )}
      </section>
    )
  }

  const detail = rule.data
  const accountsById = new Map(accounts.data.map((account) => [account.id, account]))
  const sourceAccount = accountsById.get(detail.source.connected_account_id)
  const destinationAccount = accountsById.get(detail.destination.connected_account_id)
  const destinationConnected = destinationAccount?.state === "connected"
  const disconnected = [sourceAccount, destinationAccount].some(
    (account) => account?.state === "disconnected",
  )
  const sourceName = ruleEndpointLabel(
    detail.source,
    sourceAccount,
    calendarsByAccount.get(detail.source.connected_account_id),
  ).calendar
  const destinationName = ruleEndpointLabel(
    detail.destination,
    destinationAccount,
    calendarsByAccount.get(detail.destination.connected_account_id),
  ).calendar
  const removing = removal !== undefined || detail.state === "disabled"
  const displayState = removal ? "removing" : detail.state
  const work = ruleWork({
    pending: commands.pending[detail.id],
    pendingSince: commands.pendingSince[detail.id],
    running: detail.running,
    removing: removal !== undefined,
  })
  const pending = busyCommand(commands.pending[detail.id], work)
  const run = (command: Parameters<typeof commands.run>[1]) =>
    void commands.run(detail.id, command, destinationName, () => heading.current)
  const notify = (feedback: RuleFeedback) => commands.notify(detail.id, feedback)
  const stopped = displayState === "degraded" && !disconnected

  return (
    <div className="page-section rule-details-page">
      <LiveAnnouncement text={commands.announcement} />
      {back}
      {notice && <p className="page-notice">{notice}</p>}
      <div className="page-heading-row">
        <div className="rule-heading">
          <h1 ref={heading} tabIndex={-1}>
            {sourceName} <ArrowRight aria-hidden="true" className="rule-heading-arrow" />
            <span className="sr-only"> to </span>
            {destinationName}
          </h1>
          <div className="rule-direction rule-details-direction">
            <RuleEndpoint
              account={sourceAccount}
              endpoint={detail.source}
              calendars={calendarsByAccount.get(detail.source.connected_account_id)}
              role="Source"
            />
            <ArrowRight aria-hidden="true" />
            <RuleEndpoint
              account={destinationAccount}
              endpoint={detail.destination}
              calendars={calendarsByAccount.get(detail.destination.connected_account_id)}
              role="Destination"
            />
          </div>
        </div>
        <div className="rule-actions">
          <RuleStatusBadge
            state={displayState}
            stopped={detail.state === "degraded" || disconnected}
            working={work?.kind}
          />
          <RuleNextAction
            state={displayState}
            disconnected={disconnected}
            pending={pending}
            describedBy={displayState === "dry_run_validated" ? "rule-preview-ready" : undefined}
            onRun={run}
            onViewChange={onViewChange}
          />
          <RuleCommandMenu
            state={displayState}
            disconnected={disconnected}
            pending={pending}
            source={sourceName}
            destination={destinationName}
            onRun={run}
          />
        </div>
      </div>

      {stopped && (
        <div className="rule-recovery-note">
          <ShieldAlert aria-hidden="true" />
          <p>{recoveryExplanation(detail.last_sync, now)}</p>
        </div>
      )}
      {displayState === "dry_run_validated" && (
        <PreviewReadyNote id="rule-preview-ready" preview={detail.latest_preview} destination={destinationName} />
      )}
      {/* Removal shows its own progress in the removal section. */}
      {work && work.kind !== "removal" ? (
        <RuleWorkNote work={work} source={sourceName} destination={destinationName} />
      ) : (
        <RuleFeedbackNote feedback={commands.feedback[detail.id]} />
      )}

      {detail.reprojection_required && PREVIEWABLE_STATES.includes(displayState) && (
        <div className="rule-recovery-note">
          <ShieldAlert aria-hidden="true" />
          <p>
            <strong>Preview required.</strong> The policy changed. Preview this rule, then start syncing;{" "}
            {plural(detail.mapping_count, "existing projection")} will be rewritten on the next run.
          </p>
        </div>
      )}

      <section className="rule-section" aria-labelledby="rule-facts-title">
        <h2 id="rule-facts-title">What this rule does</h2>
        <dl className="rule-facts">
          <div>
            <dt>Event information</dt>
            <dd>
              {detail.privacy_policy === "busy_only"
                ? "Busy only: titles, descriptions, and locations stay private"
                : "Title, description, and location are copied"}
            </dd>
          </div>
          <div>
            <dt>All-day events</dt>
            <dd>{detail.sync_all_day_events ? "Included" : "Excluded; timed events only"}</dd>
          </div>
          <div>
            <dt>Events you answered Maybe</dt>
            <dd>{tentativeFact(detail)}</dd>
          </div>
          <div>
            <dt>Invitations you haven't answered</dt>
            <dd>{unansweredFact(detail)}</dd>
          </div>
          <div>
            <dt>Declined events</dt>
            <dd>Not synced</dd>
          </div>
          <div>
            <dt>Starting point</dt>
            <dd>Includes events from the past {plural(detail.initial_lookback_days, "day")} onward</dd>
          </div>
          <div>
            <dt>Projections</dt>
            <dd>{plural(detail.mapping_count, "projection")} this rule manages in {destinationName}</dd>
          </div>
        </dl>
      </section>

      <section className="rule-section" aria-labelledby="rule-runs-title">
        <div className="section-heading section-heading-inline">
          <h2 id="rule-runs-title">Latest runs</h2>
          <a
            className="text-link"
            href={`${appPathForView("activity")}${activitySearch(detail.id)}`}
            onClick={(event) => {
              if (!isPlainLeftClick(event)) return
              event.preventDefault()
              onViewChange("activity", { search: activitySearch(detail.id) })
            }}
          >
            This rule's activity <ArrowRight aria-hidden="true" />
          </a>
        </div>
        <dl className="rule-facts">
          <OutcomeFact
            label="Last sync"
            explanation={`Applies changes made in ${sourceName} since the previous run. Runs every five minutes.`}
            outcome={detail.last_sync}
            kind="sync"
            now={now}
          />
          <OutcomeFact
            label="Last reconciliation"
            explanation={`Compares the events this rule wrote to ${destinationName} from the past ${plural(detail.initial_lookback_days, "day")} onward with their sources and reports any that differ, without changing them. Runs when you choose Reconcile now.`}
            outcome={detail.last_reconciliation}
            kind="reconciliation"
            now={now}
          />
        </dl>
      </section>

      {!removing && <PolicyEditor detail={detail} destinationName={destinationName} onSaved={notify} />}
      {!removing && (
        <CalendarReplacement
          detail={detail}
          accounts={accounts.data}
          destinationName={destinationName}
          destinationConnected={destinationConnected}
          onReplaced={(nextRuleId, message) => onOpenRule(nextRuleId, { notice: message })}
        />
      )}
      <RuleRemoval
        detail={detail}
        destinationName={destinationName}
        destinationConnected={destinationConnected}
        onRemoved={(outcome) => {
          onViewChange("rules", { notice: outcome.message, noticeTone: outcome.attention ? "attention" : undefined })
        }}
      />
    </div>
  )
}

function OutcomeFact({
  label,
  explanation,
  outcome,
  kind,
  now,
}: {
  label: string
  explanation: string
  outcome: RunOutcome | null
  kind: "sync" | "reconciliation"
  now: number
}) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        {runOutcomeSummary(outcome, kind)}
        {outcome && (
          <time
            dateTime={outcome.completed_at}
            className="rule-fact-time"
            title={new Date(outcome.completed_at).toLocaleString()}
          >
            {relativeTime(outcome.completed_at, now)}
          </time>
        )}
        <span className="rule-fact-explanation">{explanation}</span>
      </dd>
    </div>
  )
}

/** Focuses the first field when a form opens and returns focus to its toggle when it closes. */
function useDisclosureFocus(
  open: boolean,
  first: RefObject<HTMLElement | null>,
  toggle: RefObject<HTMLElement | null>,
) {
  const wasOpen = useRef(open)
  useEffect(() => {
    if (open) first.current?.focus()
    else if (wasOpen.current) toggle.current?.focus()
    wasOpen.current = open
  }, [open, first, toggle])
}

function useRuleInvalidation(ruleId: string) {
  const queryClient = useQueryClient()
  return async () => {
    await Promise.all(
      [...RULE_CHANGE_QUERIES, ["rule", ruleId]].map((queryKey) => queryClient.invalidateQueries({ queryKey })),
    )
  }
}

function useRuleExit(ruleId: string) {
  const queryClient = useQueryClient()
  return async () => {
    queryClient.removeQueries({ queryKey: ["rule", ruleId] })
    await Promise.all(
      RULE_CHANGE_QUERIES.map((queryKey) => queryClient.invalidateQueries({ queryKey })),
    )
  }
}

function PolicyEditor({
  detail,
  destinationName,
  onSaved,
}: {
  detail: RuleDetail
  destinationName: string
  onSaved: (feedback: RuleFeedback) => void
}) {
  const invalidate = useRuleInvalidation(detail.id)
  const toggle = useRef<HTMLButtonElement>(null)
  const firstField = useRef<HTMLSelectElement>(null)
  const current: RulePolicyPayload = {
    privacy_policy: detail.privacy_policy,
    sync_all_day_events: detail.sync_all_day_events,
    tentative_events: detail.tentative_events,
    unanswered_invitations: detail.unanswered_invitations,
  }
  const [open, setOpen] = useState(false)
  const [next, setNext] = useState<RulePolicyPayload>(current)
  const changed = policyChanged(current, next)
  // Showing details to everyone who can see the destination is the one change that widens access.
  const widens = current.privacy_policy === "busy_only" && next.privacy_policy === "copy_details"
  const update = useMutation({
    mutationFn: () => api.updateRulePolicy(detail.id, next),
    onSuccess: async () => {
      await invalidate()
      setOpen(false)
      onSaved({ tone: "success", text: "Policy saved. Preview the rule to start syncing with the new policy." })
    },
  })

  useDisclosureFocus(open, firstField, toggle)

  function cancel() {
    setOpen(false)
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    if (changed) update.mutate()
  }

  return (
    <section className="rule-section" aria-labelledby="policy-title">
      <div className="section-heading">
        <div>
          <h2 id="policy-title">What {destinationName} shows</h2>
          <p>A change stops the rule from writing until you preview it again.</p>
        </div>
        {!open && (
          <Button
            ref={toggle}
            variant="outline"
            onClick={() => {
              setNext(current)
              update.reset()
              setOpen(true)
            }}
            aria-expanded={open}
            aria-controls="policy-form"
          >
            Change policy
          </Button>
        )}
      </div>
      {open && (
        <form id="policy-form" className="rule-edit-form" onSubmit={submit}>
          <div className="field-stack">
            <Label htmlFor="edit-privacy-policy">Event information</Label>
            <NativeSelect
              ref={firstField}
              id="edit-privacy-policy"
              value={next.privacy_policy}
              onChange={(event) =>
                setNext({ ...next, privacy_policy: event.target.value as RulePolicyPayload["privacy_policy"] })
              }
            >
              <option value="busy_only">Busy only (recommended)</option>
              <option value="copy_details">Copy title, description, and location</option>
            </NativeSelect>
          </div>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={next.sync_all_day_events}
              onChange={(event) => setNext({ ...next, sync_all_day_events: event.target.checked })}
            />
            <span>
              <strong>Sync all-day events</strong>
              <small>Turn this off to synchronize timed events only.</small>
            </span>
          </label>
          <InvitationResponseFields
            idPrefix="edit-"
            policy={next}
            onChange={(change) => setNext({ ...next, ...change })}
          />
          {changed && (
            <div className="consequence-panel" data-tone={widens ? "attention" : undefined} role="status" aria-live="polite">
              <h3>{widens ? `Everyone who can see ${destinationName} will see event details` : "What happens when you save"}</h3>
              <ul>
                {policyChangeConsequences({
                  state: detail.state,
                  current,
                  next,
                  mappingCount: detail.mapping_count,
                  destination: destinationName,
                }).map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </div>
          )}
          {update.error && <div className="inline-error" role="alert">{update.error.message}</div>}
          <div className="form-actions">
            <Button type="submit" disabled={!changed || update.isPending}>
              {update.isPending ? "Saving…" : widens ? `Show event details in ${destinationName}` : "Save policy change"}
            </Button>
            <Button type="button" variant="outline" onClick={cancel} disabled={update.isPending}>
              Cancel
            </Button>
          </div>
        </form>
      )}
    </section>
  )
}

function ProjectionChoice({
  name,
  value,
  onChange,
  firstField,
  mappingCount,
  destinationName,
  deleteAvailable,
}: {
  name: string
  value: ProjectionHandling
  onChange: (value: ProjectionHandling) => void
  firstField?: RefObject<HTMLInputElement | null>
  mappingCount: number
  destinationName: string
  deleteAvailable: boolean
}) {
  return (
    <fieldset className="projection-choice" aria-describedby={`${name}-consequence`}>
      <legend>Projections this rule wrote</legend>
      <div className="radio-options">
        <label className="radio-row">
          <input
            ref={value === "delete" ? firstField : undefined}
            type="radio"
            name={name}
            value="delete"
            checked={value === "delete"}
            disabled={!deleteAvailable}
            onChange={() => onChange("delete")}
          />
          <span>
            <strong>
              Delete {plural(mappingCount, "projection")} from {destinationName} (recommended)
            </strong>
            <small>
              {deleteAvailable
                ? "Only events this rule manages are deleted."
                : "Reauthorize the destination account in Settings to delete projections."}
            </small>
          </span>
        </label>
        <label className="radio-row">
          <input
            ref={value === "detach" ? firstField : undefined}
            type="radio"
            name={name}
            value="detach"
            checked={value === "detach"}
            onChange={() => onChange("detach")}
          />
          <span>
            <strong>Keep them as ordinary events</strong>
            <small>They stay in {destinationName} and are never updated or deleted again.</small>
          </span>
        </label>
      </div>
      <p id={`${name}-consequence`} className="consequence-text">
        {removalConsequence(value, mappingCount, destinationName)}
      </p>
    </fieldset>
  )
}

function CalendarReplacement({
  detail,
  accounts,
  destinationName,
  destinationConnected,
  onReplaced,
}: {
  detail: RuleDetail
  accounts: ConnectedAccount[]
  destinationName: string
  destinationConnected: boolean
  onReplaced: (ruleId: string, notice: string) => void
}) {
  const invalidate = useRuleInvalidation(detail.id)
  const leave = useRuleExit(detail.id)
  const connected = accounts.filter((account) => account.state === "connected")
  const returnFocus = useRef<HTMLButtonElement>(null)
  const toggle = useRef<HTMLButtonElement>(null)
  const firstField = useRef<HTMLSelectElement>(null)
  const [open, setOpen] = useState(false)
  const [confirming, setConfirming] = useState(false)
  useDisclosureFocus(open, firstField, toggle)
  const [sourceAccount, setSourceAccount] = useState(detail.source.connected_account_id)
  const [sourceCalendar, setSourceCalendar] = useState(detail.source.calendar_id)
  const [destinationAccount, setDestinationAccount] = useState(detail.destination.connected_account_id)
  const [destinationCalendar, setDestinationCalendar] = useState(detail.destination.calendar_id)
  const [handling, setHandling] = useState<ProjectionHandling>("delete")
  const effective: ProjectionHandling = destinationConnected ? handling : "detach"
  const sourceCalendars = useQuery({
    queryKey: ["calendars", sourceAccount],
    queryFn: () => api.calendars(sourceAccount),
    staleTime: 5 * 60 * 1000,
    enabled: open && connected.some((account) => account.id === sourceAccount),
  })
  const destinationCalendars = useQuery({
    queryKey: ["calendars", destinationAccount],
    queryFn: () => api.calendars(destinationAccount),
    staleTime: 5 * 60 * 1000,
    enabled: open && connected.some((account) => account.id === destinationAccount),
  })
  const unchanged =
    sourceAccount === detail.source.connected_account_id &&
    sourceCalendar === detail.source.calendar_id &&
    destinationAccount === detail.destination.connected_account_id &&
    destinationCalendar === detail.destination.calendar_id
  const sameEndpoint = sourceAccount === destinationAccount && sourceCalendar === destinationCalendar
  const replace = useMutation({
    mutationFn: () =>
      api.replaceRuleCalendars(detail.id, {
        source: { connected_account_id: sourceAccount, calendar_id: sourceCalendar },
        destination: { connected_account_id: destinationAccount, calendar_id: destinationCalendar },
        projections: effective,
      }),
    onSuccess: async (result) => {
      const outcome = removalOutcome(result, destinationName)
      onReplaced(
        result.rule.id,
        `Calendars replaced. This is the new draft rule; preview it before it starts syncing.${outcome.attention ? ` ${outcome.message.replace("The rule was removed. ", "")}` : ""}`,
      )
      await leave()
    },
    // An interrupted replacement leaves the new draft and a retryable old rule behind.
    onError: invalidate,
  })
  const canSubmit = !unchanged && !sameEndpoint && Boolean(sourceCalendar && destinationCalendar)

  function submit(event: FormEvent) {
    event.preventDefault()
    if (canSubmit) setConfirming(true)
  }

  function edited<T>(apply: (value: T) => void) {
    return (value: T) => {
      apply(value)
      setConfirming(false)
    }
  }

  return (
    <section className="rule-section" aria-labelledby="replace-title">
      <div className="section-heading">
        <div>
          <h2 id="replace-title">Calendars</h2>
          <p>Changing a calendar removes this rule and creates a new draft with the same policy.</p>
        </div>
        {!open && (
          <Button
            ref={toggle}
            variant="outline"
            onClick={() => {
              replace.reset()
              setOpen(true)
            }}
            aria-expanded={open}
            aria-controls="replace-form"
          >
            Replace calendars…
          </Button>
        )}
      </div>
      {open && (
        <form id="replace-form" className="rule-edit-form" onSubmit={submit}>
          <EndpointFields
            legend="Source calendar"
            idPrefix="replace-source"
            firstField={firstField}
            accounts={connected}
            account={sourceAccount}
            calendar={sourceCalendar}
            calendars={sourceCalendars.data}
            writableOnly={false}
            onAccount={edited((value: string) => {
              setSourceAccount(value)
              setSourceCalendar("")
            })}
            onCalendar={edited(setSourceCalendar)}
          />
          <EndpointFields
            legend="Destination calendar"
            idPrefix="replace-destination"
            accounts={connected}
            account={destinationAccount}
            calendar={destinationCalendar}
            calendars={destinationCalendars.data}
            writableOnly
            errorId={sameEndpoint ? "replace-destination-error" : undefined}
            onAccount={edited((value: string) => {
              setDestinationAccount(value)
              setDestinationCalendar("")
            })}
            onCalendar={edited(setDestinationCalendar)}
          />
          <ProjectionChoice
            name="replace-projections"
            value={effective}
            onChange={edited(setHandling)}
            mappingCount={detail.mapping_count}
            destinationName={destinationName}
            deleteAvailable={destinationConnected}
          />
          {sameEndpoint && (
            <p id="replace-destination-error" className="field-error" role="alert">
              Choose a destination different from the source calendar.
            </p>
          )}
          {replace.error && <div className="inline-error" role="alert">{replace.error.message}</div>}
          <div className="form-actions">
            <Button
              ref={returnFocus}
              type="submit"
              variant="outline"
              disabled={!canSubmit || replace.isPending}
              aria-expanded={confirming}
              aria-controls="replace-confirmation"
            >
              Review replacement
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setConfirming(false)
                setOpen(false)
              }}
              disabled={replace.isPending}
            >
              Cancel
            </Button>
          </div>
          {confirming && (
            <DestructiveConfirmation
              id="replace-confirmation"
              title="Remove this rule and create a new draft?"
              body={`${removalConsequence(effective, detail.mapping_count, destinationName)} The new draft keeps this rule's policy and needs a preview before it can be enabled.`}
              cancelLabel="Keep current rule"
              confirmLabel={replacementConfirmLabel(effective, detail.mapping_count)}
              pendingLabel="Replacing…"
              pending={replace.isPending}
              onConfirm={() => replace.mutate()}
              onCancel={() => {
                setConfirming(false)
                returnFocus.current?.focus()
              }}
            />
          )}
        </form>
      )}
    </section>
  )
}

function EndpointFields({
  legend,
  idPrefix,
  firstField,
  errorId,
  accounts,
  account,
  calendar,
  calendars,
  writableOnly,
  onAccount,
  onCalendar,
}: {
  legend: string
  idPrefix: string
  firstField?: RefObject<HTMLSelectElement | null>
  errorId?: string
  accounts: ConnectedAccount[]
  account: string
  calendar: string
  calendars: DiscoveredCalendar[] | undefined
  writableOnly: boolean
  onAccount: (value: string) => void
  onCalendar: (value: string) => void
}) {
  const options = (calendars ?? []).filter(
    (item) => !writableOnly || ["writer", "owner"].includes(item.access_role),
  )
  return (
    <fieldset className="endpoint-fields">
      <legend>{legend}</legend>
      <div className="field-stack">
        <Label htmlFor={`${idPrefix}-account`}>Google account</Label>
        <NativeSelect ref={firstField} id={`${idPrefix}-account`} value={account} onChange={(event) => onAccount(event.target.value)}>
          {accounts.map((item) => (
            <option key={item.id} value={item.id}>
              {item.display_name} ({item.email})
            </option>
          ))}
        </NativeSelect>
      </div>
      <div className="field-stack">
        <Label htmlFor={`${idPrefix}-calendar`}>{writableOnly ? "Calendar you can edit" : "Calendar"}</Label>
        <NativeSelect
          id={`${idPrefix}-calendar`}
          value={calendar}
          onChange={(event) => onCalendar(event.target.value)}
          aria-invalid={errorId ? true : undefined}
          aria-describedby={errorId}
        >
          <option value="" disabled>
            Choose a calendar
          </option>
          {options.map((item) => (
            <option key={item.id} value={item.id}>
              {item.summary}
            </option>
          ))}
        </NativeSelect>
      </div>
    </fieldset>
  )
}

function RuleRemoval({
  detail,
  destinationName,
  destinationConnected,
  onRemoved,
}: {
  detail: RuleDetail
  destinationName: string
  destinationConnected: boolean
  onRemoved: (outcome: RemovalOutcome) => void
}) {
  const invalidate = useRuleInvalidation(detail.id)
  const leave = useRuleExit(detail.id)
  const queryClient = useQueryClient()
  const returnFocus = useRef<HTMLButtonElement>(null)
  const firstField = useRef<HTMLInputElement>(null)
  const confirm = useRef<HTMLButtonElement>(null)
  const progress = useRef<HTMLDivElement>(null)
  const sessionRemoval = useActiveRemoval(detail.id)
  // The service's report outlives a reload; this session's request covers the moment before it.
  const active = reportedRemoval(detail.running, detail.mapping_count) ?? sessionRemoval
  const interrupted = detail.state === "disabled" && !active
  const [open, setOpen] = useState(false)
  const expanded = open || interrupted
  const [handling, setHandling] = useState<ProjectionHandling>("delete")
  useDisclosureFocus(open && !interrupted && !active, firstField, returnFocus)
  const effective: ProjectionHandling = destinationConnected ? handling : "detach"
  const finish = async (outcome: RemovalOutcome) => {
    // Update the cached list first so the removed rule never flashes back into view.
    queryClient.setQueryData<RuleSummary[]>(["rules"], (rules) => rules?.filter((rule) => rule.id !== detail.id))
    // The removal outlives this view; only take the administrator to the rules list if they
    // are still watching it. Activity keeps the outcome either way.
    if (isViewingRule(detail.id)) onRemoved(outcome)
    await leave()
  }
  const remove = useMutation({
    mutationKey: removalMutationKey(detail.id),
    mutationFn: (request: RemovalRequest) => api.removeRule(detail.id, request.handling),
    onSuccess: (result) => finish(removalOutcome(result, destinationName)),
    onError: async (error) => {
      // A retry that waited behind an earlier, successful attempt finds the rule already gone;
      // that attempt's counts are lost, so say what to check instead of claiming none.
      if (error instanceof ApiError && error.status === 404) {
        await finish(removalOutcomeUnknown(destinationName))
        return
      }
      await invalidate()
    },
  })
  // The confirming button leaves the page while removal runs, so keep focus on its progress.
  useEffect(() => {
    if (active) progress.current?.focus()
  }, [active])
  useEffect(() => {
    if (remove.error) confirm.current?.focus()
  }, [remove.error])

  return (
    <section className="rule-section rule-removal" aria-labelledby="removal-title" aria-busy={active ? true : undefined}>
      <div className="section-heading">
        <div>
          <h2 id="removal-title">
            {active ? "Removing rule" : interrupted ? "Removal incomplete" : "Remove rule"}
          </h2>
          <p>
            {active
              ? "The rule no longer synchronizes. Source events are never changed. Removal continues if you leave this page."
              : interrupted
                ? `Removal stopped with ${plural(detail.mapping_count, "projection")} left. Retry to finish; the rule does not synchronize meanwhile.`
                : "Removing a rule is permanent. Source events are never changed."}
          </p>
        </div>
        {!expanded && !active && (
          <Button
            ref={returnFocus}
            variant="outline"
            className="removal-toggle"
            onClick={() => setOpen(true)}
            aria-expanded={expanded}
            aria-controls="removal-form"
          >
            <Trash2 aria-hidden="true" /> Remove rule…
          </Button>
        )}
      </div>
      {active ? (
        <RemovalProgress
          ref={progress}
          request={active}
          remaining={detail.mapping_count}
          destinationName={destinationName}
        />
      ) : (
        expanded && (
          <div id="removal-form" className="rule-edit-form removal-form">
            <ProjectionChoice
              name="removal-projections"
              value={effective}
              onChange={setHandling}
              firstField={firstField}
              mappingCount={detail.mapping_count}
              destinationName={destinationName}
              deleteAvailable={destinationConnected}
            />
            <div className="form-actions">
              <Button
                ref={confirm}
                variant="destructive"
                onClick={() => remove.mutate({ handling: effective, total: detail.mapping_count })}
              >
                <Trash2 aria-hidden="true" />
                {interrupted ? "Retry removal" : removalConfirmLabel(effective, detail.mapping_count)}
              </Button>
              {!interrupted && (
                <Button variant="outline" onClick={() => setOpen(false)}>
                  Keep rule
                </Button>
              )}
            </div>
            {remove.error && <div className="inline-error" role="alert">{removalErrorMessage(remove.error)}</div>}
          </div>
        )
      )}
    </section>
  )
}

function RemovalProgress({
  ref,
  request,
  remaining,
  destinationName,
}: {
  ref: RefObject<HTMLDivElement | null>
  request: ActiveRemoval
  remaining: number
  destinationName: string
}) {
  const now = useNow(1_000)
  const { done, label } = removalProgress(request, remaining, destinationName)
  return (
    <div ref={ref} tabIndex={-1} className="removal-progress">
      <p className="removal-progress-label">
        <LoaderCircle aria-hidden="true" className="work-spinner" />
        <span>{label}</span>
      </p>
      {done !== null && (
        <progress className="removal-bar" value={done} max={request.total} aria-label={label} />
      )}
      <p className="removal-progress-meta">Running for {elapsedLabel(now - request.startedAt)}</p>
    </div>
  )
}
