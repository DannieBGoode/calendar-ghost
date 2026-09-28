import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, ArrowRight, RefreshCw, ShieldAlert, Trash2 } from "lucide-react"
import { useEffect, useRef, useState, type FormEvent, type RefObject } from "react"

import { PageSkeleton } from "@/components/page-skeleton"
import {
  EnableReview,
  LiveAnnouncement,
  RuleCommandMenu,
  RuleFeedbackNote,
  RuleNextAction,
  RuleStatusBadge,
} from "@/components/rule-commands"
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
  type RemovalResult,
  type RuleDetail,
  type RulePolicyPayload,
  type RuleSummary,
  type RunOutcome,
} from "@/lib/api"
import {
  activitySearch,
  appPathForView,
  isPlainLeftClick,
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
  replacementConfirmLabel,
  runOutcomeSummary,
} from "@/lib/rule-change"
import { ruleEndpointLabel } from "@/lib/rule-endpoint"
import { relativeTime } from "@/lib/relative-time"
import { recoveryExplanation } from "@/lib/rule-run"
import { useNow } from "@/lib/use-now"
import { useRuleCommands, type RuleFeedback } from "@/lib/use-rule-commands"

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
  const rule = useQuery({
    queryKey: ["rule", ruleId],
    queryFn: () => api.rule(ruleId),
    retry: false,
    refetchInterval: 60_000,
  })
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

  // Wait for calendar names so the focused heading never announces placeholder names.
  const namesReady = calendarQueries.every((query) => !query.isPending)
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
  if (rule.error || accounts.error) {
    const missing = rule.error instanceof ApiError && rule.error.status === 404
    return (
      <section className="page-section" role="alert">
        {back}
        <h1>{missing ? "This rule no longer exists" : "Rule details could not load"}</h1>
        <p className="page-intro">
          {missing
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
    detail.source.calendar_id,
    sourceAccount,
    calendarsByAccount.get(detail.source.connected_account_id),
  ).calendar
  const destinationName = ruleEndpointLabel(
    detail.destination.calendar_id,
    destinationAccount,
    calendarsByAccount.get(detail.destination.connected_account_id),
  ).calendar
  const removing = detail.state === "disabled"
  const pending = commands.pending[detail.id]
  const run = (command: Parameters<typeof commands.run>[1]) =>
    void commands.run(detail.id, command, destinationName, () => heading.current)
  const notify = (feedback: RuleFeedback) => commands.notify(detail.id, feedback)
  const stopped = detail.state === "degraded" && !disconnected

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
              accountId={detail.source.connected_account_id}
              calendarId={detail.source.calendar_id}
              calendars={calendarsByAccount.get(detail.source.connected_account_id)}
              role="Source"
            />
            <ArrowRight aria-hidden="true" />
            <RuleEndpoint
              account={destinationAccount}
              accountId={detail.destination.connected_account_id}
              calendarId={detail.destination.calendar_id}
              calendars={calendarsByAccount.get(detail.destination.connected_account_id)}
              role="Destination"
            />
          </div>
        </div>
        <div className="rule-actions">
          <RuleStatusBadge state={detail.state} stopped={detail.state === "degraded" || disconnected} />
          <RuleNextAction
            state={detail.state}
            disconnected={disconnected}
            pending={pending}
            onRun={run}
            onViewChange={onViewChange}
          />
          <RuleCommandMenu
            state={detail.state}
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
      {detail.state === "dry_run_validated" && (
        <EnableReview
          preview={detail.latest_preview}
          source={sourceName}
          destination={destinationName}
          privacy={detail.privacy_policy}
          pending={pending}
          onEnable={() => run("enable")}
        />
      )}
      <RuleFeedbackNote pending={pending} feedback={commands.feedback[detail.id]} />

      {detail.reprojection_required && PREVIEWABLE_STATES.includes(detail.state) && (
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
            explanation={`Checks every event this rule wrote to ${destinationName} and repairs any edited or deleted there. Runs once a day.`}
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
        onRemoved={(result) => {
          const outcome = removalOutcome(result, destinationName)
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
      [["rule", ruleId], ["rules"], ["dashboard"], ["activity"], ["accounts"]].map((queryKey) =>
        queryClient.invalidateQueries({ queryKey }),
      ),
    )
  }
}

function useRuleExit(ruleId: string) {
  const queryClient = useQueryClient()
  return async () => {
    queryClient.removeQueries({ queryKey: ["rule", ruleId] })
    await Promise.all(
      [["rules"], ["dashboard"], ["activity"], ["accounts"]].map((queryKey) =>
        queryClient.invalidateQueries({ queryKey }),
      ),
    )
  }
}

function DestructiveConfirmation({
  id,
  title,
  body,
  cancelLabel,
  confirmLabel,
  pendingLabel,
  pending,
  onConfirm,
  onCancel,
}: {
  id: string
  title: string
  body: string
  cancelLabel: string
  confirmLabel: string
  pendingLabel: string
  pending: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    heading.current?.focus()
  }, [])
  return (
    <div className="disconnect-confirmation delete-confirmation" id={id} role="group" aria-labelledby={`${id}-title`}>
      <div>
        <h3 id={`${id}-title`} ref={heading} tabIndex={-1}>
          {title}
        </h3>
        <p>{body}</p>
      </div>
      <div className="confirmation-actions">
        <Button type="button" variant="outline" onClick={onCancel} disabled={pending}>
          {cancelLabel}
        </Button>
        <Button type="button" variant="destructive" onClick={onConfirm} disabled={pending}>
          <Trash2 aria-hidden="true" />
          {pending ? pendingLabel : confirmLabel}
        </Button>
      </div>
    </div>
  )
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
  onRemoved: (result: RemovalResult) => void
}) {
  const invalidate = useRuleInvalidation(detail.id)
  const leave = useRuleExit(detail.id)
  const queryClient = useQueryClient()
  const returnFocus = useRef<HTMLButtonElement>(null)
  const firstField = useRef<HTMLInputElement>(null)
  const removing = detail.state === "disabled"
  const [open, setOpen] = useState(removing)
  const [handling, setHandling] = useState<ProjectionHandling>("delete")
  useDisclosureFocus(open && !removing, firstField, returnFocus)
  const effective: ProjectionHandling = destinationConnected ? handling : "detach"
  const remove = useMutation({
    mutationFn: () => api.removeRule(detail.id, effective),
    onSuccess: async (result) => {
      // Update the cached list first so the removed rule never flashes back into view.
      queryClient.setQueryData<RuleSummary[]>(["rules"], (rules) => rules?.filter((rule) => rule.id !== detail.id))
      onRemoved(result)
      await leave()
    },
    onError: async () => {
      await invalidate()
    },
  })

  return (
    <section className="rule-section rule-removal" aria-labelledby="removal-title">
      <div className="section-heading">
        <div>
          <h2 id="removal-title">{removing ? "Removal incomplete" : "Remove rule"}</h2>
          <p>
            {removing
              ? `Removal stopped with ${plural(detail.mapping_count, "projection")} left. Retry to finish; the rule does not synchronize meanwhile.`
              : "Removing a rule is permanent. Source events are never changed."}
          </p>
        </div>
        {!open && (
          <Button
            ref={returnFocus}
            variant="outline"
            className="removal-toggle"
            onClick={() => setOpen(true)}
            aria-expanded={open}
            aria-controls="removal-form"
          >
            <Trash2 aria-hidden="true" /> Remove rule…
          </Button>
        )}
      </div>
      {open && (
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
            <Button variant="destructive" onClick={() => remove.mutate()} disabled={remove.isPending}>
              <Trash2 aria-hidden="true" />
              {remove.isPending ? "Removing…" : removing ? "Retry removal" : removalConfirmLabel(effective, detail.mapping_count)}
            </Button>
            {!removing && (
              <Button variant="outline" onClick={() => setOpen(false)} disabled={remove.isPending}>
                Keep rule
              </Button>
            )}
          </div>
          {remove.error && <div className="inline-error" role="alert">{remove.error.message}</div>}
        </div>
      )}
    </section>
  )
}
