import { useQuery } from "@tanstack/react-query"
import { ChevronDown, ChevronUp, ExternalLink, Repeat, X } from "lucide-react"
import { useEffect, useRef, type KeyboardEvent, type RefObject } from "react"

import { EventWhen } from "@/components/activity-event"
import { Button } from "@/components/ui/button"
import { HappenedLabel, RuleDirection } from "@/features/activity-labels"
import {
  describeEntry,
  entryInspection,
  eventCell,
  CHANGE_VALUES_UNAVAILABLE,
  changeListing,
  eventLookupFailure,
  formatEventTime,
  formatRunTime,
  REMOVED_RULE_LOOKUP,
  type RuleNames,
} from "@/lib/activity"
import { ruleNames, type RuleContext } from "@/lib/activity-rule-context"
import { api, type AuditEntry, type EventSnapshot } from "@/lib/api"
import type { OpenRule } from "@/lib/navigation"

export function ActivityDetail({
  entry,
  loading,
  context,
  focusRef,
  onClose,
  onOpenRule,
  onNewer,
  onOlder,
}: {
  entry: AuditEntry | undefined
  loading: boolean
  context: RuleContext
  focusRef: RefObject<boolean>
  onClose: () => void
  onOpenRule: OpenRule
  onNewer?: (() => void) | undefined
  onOlder?: (() => void) | undefined
}) {
  const close = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") onClose()
  }
  const toolbar = (
    <div className="activity-detail-bar">
      <Button variant="ghost" size="sm" onClick={onClose}>
        <X aria-hidden="true" /> Close
      </Button>
      <div className="activity-detail-steps">
        <Button variant="ghost" size="sm" onClick={onNewer} disabled={!onNewer} aria-label="Newer entry">
          <ChevronUp aria-hidden="true" />
        </Button>
        <Button variant="ghost" size="sm" onClick={onOlder} disabled={!onOlder} aria-label="Older entry">
          <ChevronDown aria-hidden="true" />
        </Button>
      </div>
    </div>
  )

  if (!entry) {
    return (
      <aside className="activity-detail" aria-label="Entry details" onKeyDown={close}>
        {toolbar}
        <p className="activity-event-status" role="status">
          {loading ? "Loading this entry…" : "This entry is no longer in the activity history."}
        </p>
      </aside>
    )
  }
  return (
    <aside className="activity-detail" aria-labelledby="activity-detail-title" onKeyDown={close}>
      {toolbar}
      <EntryDetails entry={entry} context={context} focusRef={focusRef} onOpenRule={onOpenRule} />
    </aside>
  )
}

function EntryDetails({
  entry,
  context,
  focusRef,
  onOpenRule,
}: {
  entry: AuditEntry
  context: RuleContext
  focusRef: RefObject<boolean>
  onOpenRule: OpenRule
}) {
  const headingRef = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    if (!focusRef.current) return
    focusRef.current = false
    headingRef.current?.focus({ preventScroll: true })
  }, [entry, focusRef])
  const names = ruleNames(entry.rule_id, context)
  const copy = describeEntry(entry, names)
  const exists = names !== null
  const inspection = entryInspection(entry, exists)
  return (
    <>
      <EntryHeading entry={entry} names={names} copy={copy} headingRef={headingRef} onOpenRule={onOpenRule} />
      <dl className="activity-detail-facts">
        <div>
          <dt>Recorded</dt>
          <dd>{formatRunTime(entry.occurred_at)}</dd>
        </div>
        <div>
          <dt>Rule</dt>
          <dd><RuleDirection ruleId={entry.rule_id} context={context} /></dd>
        </div>
      </dl>
      {entry.changed_fields?.length ? <SourceChangeDetails entry={entry} names={names} /> : null}
      {inspection === "event" ? (
        <ActivityEventDetails entry={entry} />
      ) : (
        entry.source_event_id && <p className="activity-event-status">{REMOVED_RULE_LOOKUP}</p>
      )}
      <EntryDiagnostics entry={entry} explanation={copy.explanation} />
    </>
  )
}

function EntryHeading({
  entry,
  names,
  copy,
  headingRef,
  onOpenRule,
}: {
  entry: AuditEntry
  names: RuleNames | null
  copy: ReturnType<typeof describeEntry>
  headingRef: RefObject<HTMLHeadingElement | null>
  onOpenRule: OpenRule
}) {
  const cell = eventCell(entry, names)
  const exists = names !== null
  return (
    <div className="activity-detail-heading">
      {/* The event is what people recognise, so it leads; what happened follows. */}
      <h2 id="activity-detail-title" ref={headingRef} tabIndex={-1}>
        {cell.state === "event" ? cell.title : cell.label}
      </h2>
      {cell.state === "event" && <EventWhen cell={cell} />}
      <HappenedLabel entry={entry} names={names} />
      {copy.explanation && <p className="activity-explanation">{copy.explanation}</p>}
      {copy.next && exists && (
        <p className="activity-next">
          <strong>What to do: </strong>
          {copy.next}
        </p>
      )}
      {entry.category === "blocked" && exists && (
        <Button variant="outline" size="sm" onClick={() => onOpenRule(entry.rule_id)}>
          Open rule
        </Button>
      )}
    </div>
  )
}

function EntryDiagnostics({ entry, explanation }: { entry: AuditEntry; explanation: string }) {
  return (
    <details className="activity-diagnostics">
      <summary>Technical details</summary>
      <dl>
        <Diagnostic label="Entry" value={String(entry.id)} />
        <Diagnostic label="Run" value={entry.run_id} />
        <Diagnostic label="Decision" value={[entry.action, entry.reason].filter(Boolean).join(" · ")} />
        <Diagnostic label="Source event ID" value={entry.source_event_id} />
        <Diagnostic label="Projection event ID" value={entry.destination_event_id} />
        {entry.detail && entry.detail !== explanation && <Diagnostic label="Recorded detail" value={entry.detail} />}
      </dl>
    </details>
  )
}

function Diagnostic({ label, value }: { label: string; value: string | null }) {
  if (!value) return null
  return (
    <div>
      <dt>{label}</dt>
      <dd><code>{value}</code></dd>
    </div>
  )
}

/** What the entry's run saw change in the source event, with the values before and after. */
function SourceChangeDetails({ entry, names }: { entry: AuditEntry; names: RuleNames | null }) {
  const change = useQuery({
    queryKey: ["activity-changes", entry.id],
    queryFn: () => api.activityChanges(entry.id),
    staleTime: Infinity,
    retry: false,
  })
  const heading = `What changed in ${names?.source ?? "the source calendar"}`
  if (change.isPending) return <p className="activity-event-status" role="status">Loading what changed…</p>
  if (change.error) {
    return <p className="activity-event-status" role="alert">What changed could not be loaded right now.</p>
  }
  return (
    <section className="activity-changes" aria-label={heading}>
      <h3>{heading}</h3>
      <dl>
        {changeListing(change.data).map((lines) => {
          return (
            <div key={lines.field}>
              <dt>{lines.label}</dt>
              <dd>
                {lines.unavailable && <span className="activity-event-status">No longer available</span>}
                {lines.before !== null && (
                  <span className="activity-change-value">
                    <span className="activity-change-label">Before</span> {lines.before}
                  </span>
                )}
                {lines.after !== null && (
                  <span className="activity-change-value">
                    <span className="activity-change-label">After</span> {lines.after}
                  </span>
                )}
                {lines.added.length > 0 && (
                  <span className="activity-change-value">
                    <span className="activity-change-label">Added</span> {lines.added.join(", ")}
                  </span>
                )}
                {lines.removed.length > 0 && (
                  <span className="activity-change-value">
                    <span className="activity-change-label">Removed</span> {lines.removed.join(", ")}
                  </span>
                )}
              </dd>
            </div>
          )
        })}
      </dl>
      {!change.data.values_available && <p className="activity-event-status">{CHANGE_VALUES_UNAVAILABLE}</p>}
    </section>
  )
}

function ActivityEventDetails({ entry }: { entry: AuditEntry }) {
  const event = useQuery({
    queryKey: ["activity-event", entry.id],
    queryFn: () => api.activityEvent(entry.id),
    staleTime: 60_000,
    retry: false,
  })
  if (event.isPending) return <p className="activity-event-status" role="status">Looking up the event in Google…</p>
  if (event.error) {
    return (
      <p className="activity-event-status" role="alert">
        {eventLookupFailure(event.error)}
      </p>
    )
  }
  return (
    <dl className="activity-event">
      <EventFacts label="Source event" snapshot={event.data.source} />
      {event.data.destination && <EventFacts label="Managed projection" snapshot={event.data.destination} />}
    </dl>
  )
}

function EventFacts({ label, snapshot }: { label: string; snapshot: EventSnapshot }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        {!snapshot.found ? (
          <span className="activity-event-missing">No longer exists in Google Calendar.</span>
        ) : (
          <>
            <strong>{snapshot.title || (snapshot.cancelled ? "Cancelled event" : "(No title)")}</strong>
            <span>
              {[snapshot.cancelled ? "Cancelled" : "", formatEventTime(snapshot)].filter(Boolean).join(" · ")}
              {snapshot.recurring && <span className="activity-recurring"><Repeat aria-hidden="true" /> Repeats</span>}
            </span>
          </>
        )}
        {snapshot.web_link && (
          <a href={snapshot.web_link} target="_blank" rel="noreferrer" className="activity-link">
            Open in Google Calendar <ExternalLink aria-hidden="true" />
          </a>
        )}
      </dd>
    </div>
  )
}
