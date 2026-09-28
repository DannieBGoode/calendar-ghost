import { useInfiniteQuery, useQueries, useQuery } from "@tanstack/react-query"
import { Activity, ArrowRight, ChevronDown, ExternalLink, RefreshCw, Repeat, ShieldAlert } from "lucide-react"
import { useId, useState } from "react"

import { PageSkeleton } from "@/components/page-skeleton"
import { RuleEndpoint } from "@/components/rule-endpoint"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { NativeSelect } from "@/components/ui/native-select"
import {
  CATEGORY_FILTERS,
  describeEntry,
  formatEventTime,
  formatRunTime,
  groupRuns,
  outcomeLabel,
  summarizeRun,
} from "@/lib/activity"
import {
  activityFailure,
  activityFailureActions,
  activityFailureMessages,
  activityFailureRequiresReload,
} from "@/lib/activity-failure"
import {
  ACTIVITY_PAGE_SIZE,
  ApiError,
  api,
  type ActivityCategory,
  type AuditEntry,
  type ConnectedAccount,
  type DiscoveredCalendar,
  type EventSnapshot,
  type Rule,
} from "@/lib/api"
import { ruleEndpointLabel } from "@/lib/rule-endpoint"

type RuleContext = {
  rulesById: Map<string, Rule>
  accountsById: Map<string, ConnectedAccount>
  calendarsByAccount: Map<string, DiscoveredCalendar[] | undefined>
}

export function ActivityView() {
  const [ruleId, setRuleId] = useState("")
  const [category, setCategory] = useState<ActivityCategory | "">("")
  const activity = useInfiniteQuery({
    queryKey: ["activity", ruleId, category],
    queryFn: ({ pageParam }) =>
      api.activity({ ruleId: ruleId || undefined, category: category || undefined, before: pageParam }),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (page) => (page.length === ACTIVITY_PAGE_SIZE ? page.at(-1)?.id : undefined),
  })
  const incidents = useQuery({ queryKey: ["incidents"], queryFn: api.incidents })
  const rules = useQuery({ queryKey: ["rules"], queryFn: api.rules })
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: api.accounts })
  // Shares the Rules view cache so calendars show their names rather than Google identifiers.
  const connectedAccountIds = (accounts.data ?? [])
    .filter((account) => account.state === "connected")
    .map((account) => account.id)
  const calendarQueries = useQueries({
    queries: connectedAccountIds.map((accountId) => ({
      queryKey: ["calendars", accountId],
      queryFn: () => api.calendars(accountId),
      staleTime: 5 * 60 * 1000,
    })),
  })
  if (activity.isPending || incidents.isPending) return <PageSkeleton />

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
          <Button variant="outline" onClick={recover} disabled={refreshing && !reloadRequired}>
            <RefreshCw aria-hidden="true" />
            {refreshing && !reloadRequired ? "Trying again…" : activityFailureActions[failure]}
          </Button>
        </section>
      </div>
    )
  }

  const context: RuleContext = {
    rulesById: new Map((rules.data ?? []).map((rule) => [rule.id, rule])),
    accountsById: new Map((accounts.data ?? []).map((account) => [account.id, account])),
    calendarsByAccount: new Map(
      connectedAccountIds.map((accountId, index) => [accountId, calendarQueries[index]?.data]),
    ),
  }
  const entries = activity.data.pages.flat()
  const runs = groupRuns(entries)
  const filtered = Boolean(ruleId || category)

  return (
    <div className="page-section">
      <ActivityHeading />
      {incidents.data.length > 0 && (
        <section className="workflow">
          <div className="section-heading"><div><h2>Incidents</h2><p>Authorization and repeated provider failures that may require attention.</p></div></div>
          <div className="rule-list">
            {incidents.data.map((incident) => (
              <div className="rule-row" key={incident.id}>
                <div className="rule-details">
                  <strong>{incident.summary}</strong>
                  <div className="activity-run-meta">
                    {incident.rule_id ? <RuleDirection ruleId={incident.rule_id} context={context} /> : <span>Installation</span>}
                    <span>Updated {formatRunTime(incident.updated_at)}</span>
                  </div>
                </div>
                <Badge variant={incident.state === "open" ? "attention" : "neutral"}>{incident.state === "open" ? "Open" : "Resolved"}</Badge>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="workflow" aria-labelledby="activity-feed-title">
        <div className="section-heading activity-feed-heading">
          <div>
            <h2 id="activity-feed-title">Synchronization decisions</h2>
            <p>Every event a rule looked at, grouped by run, newest first.</p>
          </div>
          <div className="activity-filters">
            <div className="field-stack">
              <Label htmlFor="activity-rule">Rule</Label>
              <NativeSelect id="activity-rule" value={ruleId} onChange={(event) => setRuleId(event.target.value)}>
                <option value="">All rules</option>
                {(rules.data ?? []).map((rule) => (
                  <option key={rule.id} value={rule.id}>{endpointName(rule.source, context)} → {endpointName(rule.destination, context)}</option>
                ))}
              </NativeSelect>
            </div>
            <div className="field-stack">
              <Label htmlFor="activity-category">Show</Label>
              <NativeSelect id="activity-category" value={category} onChange={(event) => setCategory(event.target.value as ActivityCategory | "")}>
                {CATEGORY_FILTERS.map((filter) => <option key={filter.value} value={filter.value}>{filter.label}</option>)}
              </NativeSelect>
            </div>
          </div>
        </div>

        {runs.length === 0 ? (
          <div className="empty-panel">
            <div className="empty-icon"><Activity aria-hidden="true" /></div>
            <h2>{filtered ? "No matching activity" : "No activity yet"}</h2>
            <p>
              {filtered
                ? "No recorded decisions match these filters. Choose a different rule or show all decisions."
                : "Synchronization decisions will appear here after an enabled rule completes its first run."}
            </p>
            {filtered && <Button variant="outline" onClick={() => { setRuleId(""); setCategory("") }}>Show all activity</Button>}
          </div>
        ) : (
          <div className="activity-runs">
            {runs.map((run) => (
              <section className="activity-run" key={run.key} aria-label={`Run ${formatRunTime(run.occurredAt)}`}>
                <header className="activity-run-header">
                  <h3>{formatRunTime(run.occurredAt)}</h3>
                  <div className="activity-run-meta">
                    <RuleDirection ruleId={run.ruleId} context={context} />
                    <span>{summarizeRun(run.entries)}</span>
                  </div>
                </header>
                <ul className="activity-entries">
                  {run.entries.map((entry) => <ActivityEntryRow key={entry.id} entry={entry} />)}
                </ul>
              </section>
            ))}
          </div>
        )}

        {activity.hasNextPage && (
          <Button variant="outline" className="activity-more" onClick={() => activity.fetchNextPage()} disabled={activity.isFetchingNextPage}>
            {activity.isFetchingNextPage ? "Loading older activity…" : "Load older activity"}
          </Button>
        )}
      </section>
    </div>
  )
}

function ActivityHeading() {
  return (
    <div>
      <p className="page-context">Activity</p>
      <h1>Incidents and audit activity</h1>
      <p className="page-intro">
        What each rule did and why. Event titles are fetched from Google only when you open an
        entry and are never stored.
      </p>
    </div>
  )
}

function endpointName(endpoint: Rule["source"], context: RuleContext): string {
  return ruleEndpointLabel(
    endpoint.calendar_id,
    context.accountsById.get(endpoint.connected_account_id),
    context.calendarsByAccount.get(endpoint.connected_account_id),
  ).calendar
}

function RuleDirection({ ruleId, context }: { ruleId: string; context: RuleContext }) {
  const rule = context.rulesById.get(ruleId)
  if (!rule) return <span>Removed rule</span>
  return (
    <span className="rule-direction activity-direction">
      <RuleEndpoint
        account={context.accountsById.get(rule.source.connected_account_id)}
        accountId={rule.source.connected_account_id}
        calendarId={rule.source.calendar_id}
        calendars={context.calendarsByAccount.get(rule.source.connected_account_id)}
        role="Source"
      />
      <ArrowRight aria-label="to" />
      <RuleEndpoint
        account={context.accountsById.get(rule.destination.connected_account_id)}
        accountId={rule.destination.connected_account_id}
        calendarId={rule.destination.calendar_id}
        calendars={context.calendarsByAccount.get(rule.destination.connected_account_id)}
        role="Destination"
      />
    </span>
  )
}

const OUTCOME_VARIANT = {
  changed: "healthy",
  unchanged: "neutral",
  skipped: "outline",
  blocked: "attention",
} as const

function ActivityEntryRow({ entry }: { entry: AuditEntry }) {
  const [open, setOpen] = useState(false)
  const detailsId = useId()
  const copy = describeEntry(entry)
  return (
    <li className="activity-entry">
      <div className="activity-entry-summary">
        <Badge variant={OUTCOME_VARIANT[entry.category]} className="activity-outcome">{outcomeLabel(entry)}</Badge>
        <p>{copy.summary}</p>
        {entry.source_event_id && (
          <Button
            variant="ghost"
            size="sm"
            className="activity-toggle"
            aria-expanded={open}
            aria-controls={detailsId}
            onClick={() => setOpen((current) => !current)}
          >
            {open ? "Hide event" : "Show event"}
            <ChevronDown aria-hidden="true" data-open={open} />
          </Button>
        )}
      </div>
      {open && (
        <div className="activity-entry-details" id={detailsId}>
          {copy.explanation && <p className="activity-explanation">{copy.explanation}</p>}
          <ActivityEventDetails entry={entry} />
        </div>
      )}
    </li>
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
        {event.error instanceof ApiError && event.error.status === 503
          ? "Google is not configured, so the event cannot be looked up."
          : "Google could not return this event right now. The account may need reauthorization in Settings."}
      </p>
    )
  }
  return (
    <dl className="activity-event">
      <EventFacts label="Source event" snapshot={event.data.source} />
      {event.data.destination && <EventFacts label="Managed projection" snapshot={event.data.destination} />}
      <div className="activity-event-ids">
        <dt>Event ID</dt>
        <dd><code>{entry.source_event_id}</code></dd>
      </div>
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
        ) : snapshot.cancelled ? (
          <span className="activity-event-missing">Cancelled.</span>
        ) : (
          <>
            <strong>{snapshot.title || "(No title)"}</strong>
            <span>
              {formatEventTime(snapshot)}
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
