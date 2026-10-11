import { useQuery } from "@tanstack/react-query"
import { ChevronDown, ChevronUp, ExternalLink, Repeat, X } from "lucide-react"
import { useEffect, useRef, type KeyboardEvent, type RefObject } from "react"

import { EventWhen } from "@/components/activity-event"
import { Button } from "@/components/ui/button"
import { HappenedLabel, RuleDirection } from "@/features/activity-labels"
import { useI18n } from "@/i18n/provider"
import { rich } from "@/i18n/rich"
import {
  describeEntry,
  entryInspection,
  eventCell,
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
  const { t } = useI18n()
  const close = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") onClose()
  }
  const toolbar = (
    <div className="activity-detail-bar">
      <Button variant="ghost" size="sm" onClick={onClose}>
        <X aria-hidden="true" /> {t("activity.detail.close")}
      </Button>
      <div className="activity-detail-steps">
        <Button variant="ghost" size="sm" onClick={onNewer} disabled={!onNewer} aria-label={t("activity.detail.newer")}>
          <ChevronUp aria-hidden="true" />
        </Button>
        <Button variant="ghost" size="sm" onClick={onOlder} disabled={!onOlder} aria-label={t("activity.detail.older")}>
          <ChevronDown aria-hidden="true" />
        </Button>
      </div>
    </div>
  )

  if (!entry) {
    return (
      <aside className="activity-detail" aria-label={t("activity.detail.label")} onKeyDown={close}>
        {toolbar}
        <p className="activity-event-status" role="status">
          {loading ? t("activity.detail.loading") : t("activity.detail.missing")}
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
  const { i18n } = context
  const { t } = i18n
  const names = ruleNames(entry.rule_id, context)
  const copy = describeEntry(i18n, entry, names)
  const exists = names !== null
  const inspection = entryInspection(entry, exists)
  return (
    <>
      <EntryHeading entry={entry} names={names} copy={copy} headingRef={headingRef} onOpenRule={onOpenRule} />
      <dl className="activity-detail-facts">
        <div>
          <dt>{t("activity.detail.recorded")}</dt>
          <dd>{formatRunTime(i18n, entry.occurred_at)}</dd>
        </div>
        <div>
          <dt>{t("activity.detail.rule")}</dt>
          <dd><RuleDirection ruleId={entry.rule_id} context={context} /></dd>
        </div>
      </dl>
      {entry.changed_fields?.length ? <SourceChangeDetails entry={entry} names={names} /> : null}
      {inspection === "event" ? (
        <ActivityEventDetails entry={entry} />
      ) : (
        entry.source_event_id && <p className="activity-event-status">{t(REMOVED_RULE_LOOKUP)}</p>
      )}
      <EntryDiagnostics entry={entry} />
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
  const i18n = useI18n()
  const { t } = i18n
  const cell = eventCell(i18n, entry, names)
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
          {rich(t("activity.detail.whatToDo", { next: copy.next }), { strong: (text) => <strong>{text}</strong> })}
        </p>
      )}
      {entry.category === "blocked" && exists && (
        <Button variant="outline" size="sm" onClick={() => onOpenRule(entry.rule_id)}>
          {t("activity.detail.openRule")}
        </Button>
      )}
    </div>
  )
}

function EntryDiagnostics({ entry }: { entry: AuditEntry }) {
  const { t } = useI18n()
  return (
    <details className="activity-diagnostics">
      <summary>{t("activity.detail.diagnostics.summary")}</summary>
      <dl>
        <Diagnostic label={t("activity.detail.diagnostics.entry")} value={String(entry.id)} />
        <Diagnostic label={t("activity.detail.diagnostics.run")} value={entry.run_id} />
        <Diagnostic label={t("activity.detail.diagnostics.decision")} value={[entry.action, entry.reason].filter(Boolean).join(" · ")} />
        <Diagnostic label={t("activity.detail.diagnostics.sourceEventId")} value={entry.source_event_id} />
        <Diagnostic label={t("activity.detail.diagnostics.projectionEventId")} value={entry.destination_event_id} />
        {/* Server text, shown as recorded: never the explanation, which is always a translated sentence. */}
        <Diagnostic label={t("activity.detail.diagnostics.recordedDetail")} value={entry.detail} />
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
  const i18n = useI18n()
  const { t } = i18n
  const change = useQuery({
    queryKey: ["activity-changes", entry.id],
    queryFn: () => api.activityChanges(entry.id),
    staleTime: Infinity,
    retry: false,
  })
  const heading = t("activity.changes.heading", { source: names?.source ?? t("activity.names.source") })
  if (change.isPending) return <p className="activity-event-status" role="status">{t("activity.changes.loading")}</p>
  if (change.error) {
    return <p className="activity-event-status" role="alert">{t("activity.changes.failed")}</p>
  }
  return (
    <section className="activity-changes" aria-label={heading}>
      <h3>{heading}</h3>
      <dl>
        {changeListing(i18n, change.data).map((lines) => {
          return (
            <div key={lines.field}>
              <dt>{lines.label}</dt>
              <dd>
                {lines.unavailable && <span className="activity-event-status">{t("activity.changes.unavailable")}</span>}
                {lines.before !== null && (
                  <span className="activity-change-value">
                    <span className="activity-change-label">{t("activity.changes.before")}</span> {lines.before}
                  </span>
                )}
                {lines.after !== null && (
                  <span className="activity-change-value">
                    <span className="activity-change-label">{t("activity.changes.after")}</span> {lines.after}
                  </span>
                )}
                {lines.added.length > 0 && (
                  <span className="activity-change-value">
                    <span className="activity-change-label">{t("activity.changes.added")}</span> {i18n.format.unitList(lines.added)}
                  </span>
                )}
                {lines.removed.length > 0 && (
                  <span className="activity-change-value">
                    <span className="activity-change-label">{t("activity.changes.removed")}</span> {i18n.format.unitList(lines.removed)}
                  </span>
                )}
              </dd>
            </div>
          )
        })}
      </dl>
      {!change.data.values_available && <p className="activity-event-status">{t("activity.changes.valuesUnavailable")}</p>}
    </section>
  )
}

function ActivityEventDetails({ entry }: { entry: AuditEntry }) {
  const i18n = useI18n()
  const { t } = i18n
  const event = useQuery({
    queryKey: ["activity-event", entry.id],
    queryFn: () => api.activityEvent(entry.id),
    staleTime: 60_000,
    retry: false,
  })
  if (event.isPending) return <p className="activity-event-status" role="status">{t("activity.lookup.loading")}</p>
  if (event.error) {
    return (
      <p className="activity-event-status" role="alert">
        {eventLookupFailure(i18n, event.error)}
      </p>
    )
  }
  return (
    <dl className="activity-event">
      <EventFacts label={t("activity.lookup.sourceEvent")} snapshot={event.data.source} />
      {event.data.destination && <EventFacts label={t("activity.lookup.managedProjection")} snapshot={event.data.destination} />}
    </dl>
  )
}

function EventFacts({ label, snapshot }: { label: string; snapshot: EventSnapshot }) {
  const i18n = useI18n()
  const { t } = i18n
  const when = formatEventTime(i18n, snapshot)
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        {!snapshot.found ? (
          <span className="activity-event-missing">{t("activity.lookup.missing")}</span>
        ) : (
          <>
            <strong>{snapshot.title || t(snapshot.cancelled ? "activity.cell.cancelledEvent" : "activity.cell.noTitle")}</strong>
            <span>
              {snapshot.cancelled ? (when ? t("activity.lookup.cancelledAndWhen", { when }) : t("activity.lookup.cancelled")) : when}
              {snapshot.recurring && (
                <span className="activity-recurring">
                  <Repeat aria-hidden="true" /> {t("activity.event.repeats")}
                </span>
              )}
            </span>
          </>
        )}
        {snapshot.web_link && (
          <a href={snapshot.web_link} target="_blank" rel="noreferrer" className="activity-link">
            {t("activity.lookup.openInCalendar")} <ExternalLink aria-hidden="true" />
          </a>
        )}
      </dd>
    </div>
  )
}
