import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, ArrowRight, CircleDot, RefreshCw, ShieldAlert, Trash2 } from "lucide-react"
import { useEffect, useRef, useState, type FormEvent } from "react"

import { PageSkeleton } from "@/components/page-skeleton"
import { RuleEndpoint } from "@/components/rule-endpoint"
import { Badge } from "@/components/ui/badge"
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
  type RunOutcome,
} from "@/lib/api"
import { appPathForView, isPlainLeftClick, type AppView } from "@/lib/navigation"
import {
  plural,
  policyChanged,
  policyChangeConsequences,
  removalConfirmLabel,
  removalConsequence,
  removalOutcome,
  replacementConfirmLabel,
  ruleStateLabel,
  runOutcomeSummary,
} from "@/lib/rule-change"
import { ruleEndpointLabel } from "@/lib/rule-endpoint"
import { previewSummary } from "@/lib/rule-preview"

const PREVIEWABLE_STATES = ["draft", "paused", "degraded"]

export function RuleDetailsView({
  ruleId,
  onViewChange,
  onOpenRule,
  onRemoved,
}: {
  ruleId: string
  onViewChange: (view: AppView) => void
  onOpenRule: (ruleId: string) => void
  onRemoved: (outcome: ReturnType<typeof removalOutcome>) => void
}) {
  const rule = useQuery({ queryKey: ["rule", ruleId], queryFn: () => api.rule(ruleId), retry: false })
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

  useEffect(() => {
    if (loadedRuleId) heading.current?.focus()
  }, [loadedRuleId])

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

  if (rule.isPending || accounts.isPending) return <PageSkeleton />
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
  const destinationName = ruleEndpointLabel(
    detail.destination.calendar_id,
    destinationAccount,
    calendarsByAccount.get(detail.destination.connected_account_id),
  ).calendar
  const removing = detail.state === "disabled"
  const attention = removing || detail.state === "degraded" || disconnected

  return (
    <div className="page-section rule-details-page">
      {back}
      <div className="page-heading-row">
        <div>
          <p className="page-context">Directional Sync Rule</p>
          <h1 ref={heading} tabIndex={-1}>Rule details</h1>
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
          <Badge variant={detail.state === "enabled" && !disconnected ? "healthy" : attention ? "attention" : "neutral"}>
            {attention ? <ShieldAlert aria-hidden="true" /> : <CircleDot aria-hidden="true" />}
            {disconnected && !removing ? "Stopped" : ruleStateLabel(detail.state)}
          </Badge>
          <RuleNextAction detail={detail} disconnected={disconnected} onViewChange={onViewChange} />
        </div>
      </div>

      {detail.reprojection_required && PREVIEWABLE_STATES.includes(detail.state) && (
        <div className="rule-recovery-note" role="status">
          <ShieldAlert aria-hidden="true" />
          <p>
            <strong>Preview required.</strong> The policy changed. Preview this rule, then enable it;{" "}
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
            <dt>Initial window</dt>
            <dd>Events ending in the last {plural(detail.initial_lookback_days, "day")} or later</dd>
          </div>
          <div>
            <dt>Managed projections</dt>
            <dd>{plural(detail.mapping_count, "Event Mapping")} in {destinationName}</dd>
          </div>
        </dl>
      </section>

      <section className="rule-section" aria-labelledby="rule-runs-title">
        <h2 id="rule-runs-title">Recent runs</h2>
        <dl className="rule-facts">
          <OutcomeFact label="Last synchronization" outcome={detail.last_sync} kind="sync" />
          <OutcomeFact label="Last reconciliation" outcome={detail.last_reconciliation} kind="reconciliation" />
        </dl>
      </section>

      {!removing && <PolicyEditor detail={detail} destinationName={destinationName} />}
      {!removing && (
        <CalendarReplacement
          detail={detail}
          accounts={accounts.data}
          destinationName={destinationName}
          destinationConnected={destinationConnected}
          onReplaced={onOpenRule}
        />
      )}
      <RuleRemoval
        detail={detail}
        destinationName={destinationName}
        destinationConnected={destinationConnected}
        onRemoved={(result) => onRemoved(removalOutcome(result, destinationName))}
      />
    </div>
  )
}

function RuleNextAction({
  detail,
  disconnected,
  onViewChange,
}: {
  detail: RuleDetail
  disconnected: boolean
  onViewChange: (view: AppView) => void
}) {
  const invalidate = useRuleInvalidation(detail.id)
  const preview = useMutation({ mutationFn: () => api.previewRule(detail.id), onSuccess: invalidate })
  const enable = useMutation({ mutationFn: () => api.enableRule(detail.id), onSuccess: invalidate })
  const sync = useMutation({ mutationFn: () => api.syncRule(detail.id), onSuccess: invalidate })
  const error = preview.error ?? enable.error ?? sync.error

  let action = null
  if (detail.state === "disabled") action = null
  else if (disconnected) {
    action = (
      <Button variant="outline" onClick={() => onViewChange("settings")}>
        Reauthorize in Settings
      </Button>
    )
  } else if (PREVIEWABLE_STATES.includes(detail.state)) {
    action = (
      <Button variant="outline" onClick={() => preview.mutate()} disabled={preview.isPending}>
        {preview.isPending ? "Previewing…" : detail.state === "degraded" ? "Validate recovery" : "Preview rule"}
      </Button>
    )
  } else if (detail.state === "dry_run_validated") {
    action = (
      <Button onClick={() => enable.mutate()} disabled={enable.isPending}>
        {enable.isPending ? "Enabling…" : "Enable rule"}
      </Button>
    )
  } else if (detail.state === "enabled") {
    action = (
      <Button variant="outline" onClick={() => sync.mutate()} disabled={sync.isPending}>
        <RefreshCw aria-hidden="true" /> {sync.isPending ? "Syncing…" : "Sync now"}
      </Button>
    )
  }

  return (
    <>
      {action}
      {preview.data && (
        <p className="preview-result" role="status">
          {previewSummary(preview.data)}
        </p>
      )}
      {error && <div className="inline-error" role="alert">{error.message}</div>}
    </>
  )
}

function OutcomeFact({
  label,
  outcome,
  kind,
}: {
  label: string
  outcome: RunOutcome | null
  kind: "sync" | "reconciliation"
}) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        {runOutcomeSummary(outcome, kind)}
        {outcome && (
          <time dateTime={outcome.completed_at} className="rule-fact-time">
            {new Date(outcome.completed_at).toLocaleString()}
          </time>
        )}
      </dd>
    </div>
  )
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
        <h4 id={`${id}-title`} ref={heading} tabIndex={-1}>
          {title}
        </h4>
        <p>{body}</p>
      </div>
      <div className="confirmation-actions">
        <Button variant="outline" onClick={onCancel} disabled={pending}>
          {cancelLabel}
        </Button>
        <Button variant="destructive" onClick={onConfirm} disabled={pending}>
          <Trash2 aria-hidden="true" />
          {pending ? pendingLabel : confirmLabel}
        </Button>
      </div>
    </div>
  )
}

function PolicyEditor({ detail, destinationName }: { detail: RuleDetail; destinationName: string }) {
  const invalidate = useRuleInvalidation(detail.id)
  const current: RulePolicyPayload = {
    privacy_policy: detail.privacy_policy,
    sync_all_day_events: detail.sync_all_day_events,
  }
  const [open, setOpen] = useState(false)
  const [next, setNext] = useState<RulePolicyPayload>(current)
  const changed = policyChanged(current, next)
  const update = useMutation({
    mutationFn: () => api.updateRulePolicy(detail.id, next),
    onSuccess: async () => {
      await invalidate()
      setOpen(false)
    },
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    if (changed) update.mutate()
  }

  return (
    <section className="rule-section" aria-labelledby="policy-title">
      <div className="section-heading">
        <div>
          <h2 id="policy-title">Projection policy</h2>
          <p>Changing it is a Material Rule Change and needs a new preview.</p>
        </div>
        <Button
          variant="outline"
          onClick={() => {
            setNext(current)
            update.reset()
            setOpen((value) => !value)
          }}
          aria-expanded={open}
          aria-controls="policy-form"
        >
          {open ? "Cancel" : "Change policy"}
        </Button>
      </div>
      {open && (
        <form id="policy-form" className="rule-edit-form" onSubmit={submit}>
          <div className="field-stack">
            <Label htmlFor="edit-privacy-policy">Event information</Label>
            <NativeSelect
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
            <div className="consequence-panel" role="status" aria-live="polite">
              <h3>What happens when you save</h3>
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
              {update.isPending ? "Saving…" : "Save policy change"}
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
  mappingCount,
  destinationName,
  deleteAvailable,
}: {
  name: string
  value: ProjectionHandling
  onChange: (value: ProjectionHandling) => void
  mappingCount: number
  destinationName: string
  deleteAvailable: boolean
}) {
  return (
    <fieldset className="projection-choice">
      <legend id={`${name}-legend`}>Existing projections</legend>
      <div role="radiogroup" aria-labelledby={`${name}-legend`} aria-describedby={`${name}-consequence`}>
        <label className="radio-row">
          <input
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
  onReplaced: (ruleId: string) => void
}) {
  const invalidate = useRuleInvalidation(detail.id)
  const leave = useRuleExit(detail.id)
  const connected = accounts.filter((account) => account.state === "connected")
  const returnFocus = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [sourceAccount, setSourceAccount] = useState(detail.source.connected_account_id)
  const [sourceCalendar, setSourceCalendar] = useState(detail.source.calendar_id)
  const [destinationAccount, setDestinationAccount] = useState(detail.destination.connected_account_id)
  const [destinationCalendar, setDestinationCalendar] = useState(detail.destination.calendar_id)
  const [handling, setHandling] = useState<ProjectionHandling>("delete")
  const effective: ProjectionHandling = destinationConnected ? handling : "detach"
  const sourceCalendars = useQuery({
    queryKey: ["calendars", sourceAccount],
    queryFn: () => api.calendars(sourceAccount),
    enabled: open && connected.some((account) => account.id === sourceAccount),
  })
  const destinationCalendars = useQuery({
    queryKey: ["calendars", destinationAccount],
    queryFn: () => api.calendars(destinationAccount),
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
      onReplaced(result.rule.id)
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
        <Button
          variant="outline"
          onClick={() => {
            replace.reset()
            setOpen((value) => !value)
          }}
          aria-expanded={open}
          aria-controls="replace-form"
        >
          {open ? "Cancel" : "Change calendars"}
        </Button>
      </div>
      {open && (
        <form id="replace-form" className="rule-edit-form" onSubmit={submit}>
          <EndpointFields
            legend="Source calendar"
            idPrefix="replace-source"
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
          {sameEndpoint && <p className="field-error" role="alert">Choose a different destination calendar.</p>}
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
        <Label htmlFor={`${idPrefix}-account`}>Google identity</Label>
        <NativeSelect id={`${idPrefix}-account`} value={account} onChange={(event) => onAccount(event.target.value)}>
          {accounts.map((item) => (
            <option key={item.id} value={item.id}>
              {item.display_name} ({item.email})
            </option>
          ))}
        </NativeSelect>
      </div>
      <div className="field-stack">
        <Label htmlFor={`${idPrefix}-calendar`}>{writableOnly ? "Writable calendar" : "Calendar"}</Label>
        <NativeSelect id={`${idPrefix}-calendar`} value={calendar} onChange={(event) => onCalendar(event.target.value)}>
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
  const returnFocus = useRef<HTMLButtonElement>(null)
  const [handling, setHandling] = useState<ProjectionHandling>("delete")
  const [confirming, setConfirming] = useState(false)
  const effective: ProjectionHandling = destinationConnected ? handling : "detach"
  const remove = useMutation({
    mutationFn: () => api.removeRule(detail.id, effective),
    onSuccess: async (result) => {
      onRemoved(result)
      await leave()
    },
    onError: async () => {
      await invalidate()
    },
  })
  const removing = detail.state === "disabled"

  return (
    <section className="rule-section rule-removal" aria-labelledby="removal-title">
      <div className="section-heading">
        <div>
          <h2 id="removal-title">{removing ? "Removal incomplete" : "Remove rule"}</h2>
          <p>
            {removing
              ? `Removal stopped with ${plural(detail.mapping_count, "projection")} left. Retry to finish; the rule does not synchronize meanwhile.`
              : "Rule Removal is permanent. Choose what happens to the events this rule manages."}
          </p>
        </div>
      </div>
      <ProjectionChoice
        name="removal-projections"
        value={effective}
        onChange={(value) => {
          setHandling(value)
          setConfirming(false)
        }}
        mappingCount={detail.mapping_count}
        destinationName={destinationName}
        deleteAvailable={destinationConnected}
      />
      <div className="form-actions">
        <Button
          ref={returnFocus}
          variant="outline"
          onClick={() => setConfirming(true)}
          disabled={remove.isPending}
          aria-expanded={confirming}
          aria-controls="removal-confirmation"
        >
          <Trash2 aria-hidden="true" /> {removing ? "Retry removal" : "Remove rule"}
        </Button>
      </div>
      {confirming && (
        <DestructiveConfirmation
          id="removal-confirmation"
          title="Remove this rule permanently?"
          body={removalConsequence(effective, detail.mapping_count, destinationName)}
          cancelLabel="Keep rule"
          confirmLabel={removalConfirmLabel(effective, detail.mapping_count)}
          pendingLabel="Removing…"
          pending={remove.isPending}
          onConfirm={() => remove.mutate()}
          onCancel={() => {
            setConfirming(false)
            returnFocus.current?.focus()
          }}
        />
      )}
      {remove.error && <div className="inline-error" role="alert">{remove.error.message}</div>}
    </section>
  )
}
