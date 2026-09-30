import { keepPreviousData, useInfiniteQuery, useQueries, useQuery } from "@tanstack/react-query"
import {
  Activity,
  ArrowRight,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  RefreshCw,
  Repeat,
  Search,
  ShieldAlert,
  X,
} from "lucide-react"
import { useEffect, useRef, useState, type KeyboardEvent, type MouseEvent, type RefObject } from "react"

import { EventWhen, HappenedLine } from "@/components/activity-event"
import { PageSkeleton } from "@/components/page-skeleton"
import { RuleEndpoint } from "@/components/rule-endpoint"
import { RulePicker, type RulePickerOption } from "@/components/rule-picker"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { NativeSelect } from "@/components/ui/native-select"
import {
  activityRows,
  describeEntry,
  entryInspection,
  eventCell,
  eventLookupFailure,
  formatClockTime,
  formatDay,
  formatEventTime,
  formatRunTime,
  groupRuns,
  REMOVED_RULE_LOOKUP,
  SHOW_FILTERS,
  showCategories,
  whatHappened,
  type EventCell,
  type RuleNames,
} from "@/lib/activity"
import {
  activityFailure,
  activityFailureActions,
  activityFailureMessages,
  activityFailureRequiresReload,
} from "@/lib/activity-failure"
import {
  activitySearch,
  activityStateFromSearch,
  type ActivityLocationState,
  type ActivityShow,
} from "@/lib/activity-location"
import {
  ACTIVITY_PAGE_SIZE,
  api,
  type AuditEntry,
  type ConnectedAccount,
  type DiscoveredCalendar,
  type EventSnapshot,
  type Incident,
  type Rule,
} from "@/lib/api"
import { incidentClosedAt, incidentGuidance, incidentResolution, splitIncidents, type IncidentAction, type IncidentRuleState } from "@/lib/incidents"
import { isPlainLeftClick, type OpenRule, type ViewChange } from "@/lib/navigation"
import { plural } from "@/lib/rule-change"
import { ruleEndpointLabel } from "@/lib/rule-endpoint"

type RuleContext = {
  rulesById: Map<string, Rule>
  accountsById: Map<string, ConnectedAccount>
  calendarsByAccount: Map<string, DiscoveredCalendar[] | undefined>
  rulesLoaded: boolean
}

// Until rules load, assume a rule exists rather than hide its events.
const LOADING_NAMES: RuleNames = { source: "the source calendar", destination: "the destination" }

function ruleNames(ruleId: string, context: RuleContext): RuleNames | null {
  if (!context.rulesLoaded) return LOADING_NAMES
  const rule = context.rulesById.get(ruleId)
  if (!rule) return null
  return { source: endpointName(rule.source, context), destination: endpointName(rule.destination, context) }
}

/**
 * Filters and the open entry live in the address so Back, reload, and shared links keep them. The
 * view remounts on every arrival, including Back and Forward, so it only reads the address once.
 */
function useActivityLocation() {
  const [state, setState] = useState(() => activityStateFromSearch(window.location.search))

  function update(next: Partial<ActivityLocationState>, history: "push" | "replace") {
    const merged = { ...state, ...next }
    const url = `${window.location.pathname}${activitySearch(merged)}`
    if (history === "push") window.history.pushState(null, "", url)
    else window.history.replaceState(null, "", url)
    setState(merged)
  }

  return [state, update] as const
}


export function ActivityView({ onViewChange, onOpenRule }: { onViewChange: ViewChange; onOpenRule: OpenRule }) {
  const [state, update] = useActivityLocation()
  const { ruleId, show, entryId } = state
  const query = state.query ?? ""
  const focusDetail = useRef(false)
  const activity = useInfiniteQuery({
    queryKey: ["activity", ruleId, show, query],
    queryFn: ({ pageParam }) =>
      api.activity({
        ruleId: ruleId || undefined,
        categories: showCategories(show),
        before: pageParam,
        query: query || undefined,
      }),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (page) => (page.length === ACTIVITY_PAGE_SIZE ? page.at(-1)?.id : undefined),
    // Keep the current table on screen while another rule or filter loads.
    placeholderData: keepPreviousData,
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
  const entries = activity.data?.pages.flat() ?? []
  const runs = groupRuns(entries)
  const listedEntry = entries.find((item) => item.id === entryId)
  // A shared link or an older page can name an entry that is not loaded.
  const directEntry = useQuery({
    queryKey: ["activity-entry", entryId],
    queryFn: () => api.activityEntry(entryId as number),
    enabled: entryId !== null && listedEntry === undefined && !activity.isPending,
    retry: false,
  })
  const selected = listedEntry ?? (directEntry.data?.id === entryId ? directEntry.data : undefined)

  if (activity.isPending || incidents.isPending) return <PageSkeleton label="Loading activity" />

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
    rulesLoaded: rules.data !== undefined,
  }
  const { open: openIncidents, resolved: resolvedIncidents } = splitIncidents(incidents.data)
  const groups = activityRows(runs)
  const visibleEntries = runs.flatMap((run) => run.entries)
  const selectedIndex = selected ? visibleEntries.findIndex((item) => item.id === selected.id) : -1
  const updating = activity.isPlaceholderData
  const detailOpen = entryId !== null

  function select(entry: AuditEntry | undefined, history: "push" | "replace") {
    if (entry) update({ entryId: entry.id }, history)
  }

  function openEntry(entry: AuditEntry) {
    focusDetail.current = true
    select(entry, entryId === null ? "push" : "replace")
  }

  function closeDetail() {
    const closing = entryId
    update({ entryId: null }, "push")
    // Return focus to the row the details described.
    requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-row-link="${closing}"]`)?.focus())
  }

  function changeFilters(next: Partial<ActivityLocationState>) {
    update({ ...next, entryId: null }, "replace")
  }

  function followIncident(action: IncidentAction) {
    if (action.kind === "settings") onViewChange("settings")
    else if (action.kind === "rule") onOpenRule(action.ruleId)
    else {
      update({ ruleId: action.ruleId, show: "blocked", query: "", entryId: null }, "push")
      requestAnimationFrame(() => document.getElementById("activity-feed-title")?.scrollIntoView({ block: "start" }))
    }
  }

  function moveSelection(event: KeyboardEvent<HTMLTableElement>) {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return
    const target = event.target as HTMLElement
    if (!target.dataset.rowLink) return
    const links = [...event.currentTarget.querySelectorAll<HTMLElement>("[data-row-link]")]
    const next = links[links.indexOf(target) + (event.key === "ArrowDown" ? 1 : -1)]
    if (!next) return
    event.preventDefault()
    next.focus()
    // With details open, the arrow keys step through entries without leaving the table.
    if (detailOpen) select(visibleEntries.find((item) => String(item.id) === next.dataset.rowLink), "replace")
  }

  // A selected rule is named above the table, and the detail pane names the rule of its entry.
  const showRuleColumn = !ruleId && !detailOpen
  const columns = showRuleColumn ? 4 : 3
  const pickerOptions = rulePickerOptions(ruleId, entries, context)

  return (
    <div className="page-section">
      <ActivityHeading />
      <OpenIncidents incidents={openIncidents} context={context} onAction={followIncident} />
      <ResolvedIncidents incidents={resolvedIncidents} context={context} />

      <section className="workflow activity-section" aria-labelledby="activity-feed-title">
        <div className="section-heading activity-feed-heading">
          <div>
            <h2 id="activity-feed-title">History</h2>
            <p>Newest first. Select an entry to see what happened and why.</p>
          </div>
        </div>
        <div className="activity-filters">
            <ActivitySearch query={query} onSearch={(next) => changeFilters({ query: next })} />
            <div className="field-stack">
              <Label id="activity-rule-label" onClick={() => document.getElementById("activity-rule")?.focus()}>Rule</Label>
              <RulePicker
                id="activity-rule"
                labelId="activity-rule-label"
                value={ruleId}
                options={pickerOptions.options}
                showAccounts={pickerOptions.showAccounts}
                clearValue=""
                clearLabel="Show all rules"
                onChange={(value) => changeFilters({ ruleId: value })}
              />
            </div>
            <div className="field-stack">
              <Label htmlFor="activity-category">Show</Label>
              <NativeSelect id="activity-category" value={show} onChange={(event) => changeFilters({ show: event.target.value as ActivityShow })}>
                {SHOW_FILTERS.map((filter) => <option key={filter.value} value={filter.value}>{filter.label}</option>)}
              </NativeSelect>
            </div>
        </div>
        <p className="sr-only" role="status">
          {updating
            ? "Updating activity…"
            : query
              ? `${activity.hasNextPage ? "More than " : ""}${plural(visibleEntries.length, "entry", "entries")} found for “${query}”.`
              : ""}
        </p>

        {/* A linked entry the filters hide still opens beside an empty table. */}
        <div className="activity-layout" data-detail={detailOpen}>
          <div className="activity-table-wrap" aria-busy={updating} data-updating={updating}>
            {groups.length === 0 ? (
              <EmptyActivity
                ruleId={ruleId}
                show={show}
                query={query}
                onShowAll={() => changeFilters({ show: "all" })}
                onAllRules={() => changeFilters({ ruleId: "" })}
                onClearSearch={() => changeFilters({ query: "" })}
              />
            ) : (
              <>
                {/* Explicit roles keep table semantics where narrow screens restyle the rows. */}
                <table className="activity-table" role="table" onKeyDown={moveSelection}>
                  <caption className="sr-only">Synchronization history, newest first</caption>
                  <thead role="rowgroup">
                    <tr role="row">
                      <th scope="col" role="columnheader" className="activity-col-time">Time</th>
                      <th scope="col" role="columnheader" className="activity-col-event">Event</th>
                      <th scope="col" role="columnheader" className="activity-col-happened">What happened</th>
                      {showRuleColumn && <th scope="col" role="columnheader" className="activity-col-rule">Rule</th>}
                    </tr>
                  </thead>
                  {groups.flatMap((group) => [
                    ...(group.day
                      ? [
                          <tbody key={`${group.key}-day`} role="rowgroup" className="activity-day">
                            <tr role="row">
                              <th scope="colgroup" role="rowheader" colSpan={columns}>{group.day}</th>
                            </tr>
                          </tbody>,
                        ]
                      : []),
                    <tbody key={group.key} role="rowgroup" className="activity-run">
                      {group.run.entries.map((entry) => (
                        <EntryRow
                          key={entry.id}
                          entry={entry}
                          context={context}
                          state={state}
                          selected={entryId === entry.id}
                          showRuleColumn={showRuleColumn}
                          onOpen={openEntry}
                          onFilterRule={(value) => changeFilters({ ruleId: value })}
                        />
                      ))}
                    </tbody>,
                  ])}
                </table>
                {activity.hasNextPage && (
                  <Button variant="outline" className="activity-more" onClick={() => activity.fetchNextPage()} disabled={activity.isFetchingNextPage}>
                    {activity.isFetchingNextPage ? "Loading older activity…" : "Load older activity"}
                  </Button>
                )}
              </>
            )}
          </div>
          {detailOpen && (
            <ActivityDetail
              entry={selected}
              loading={selected === undefined && (directEntry.isPending || directEntry.isFetching)}
              context={context}
              focusRef={focusDetail}
              onClose={closeDetail}
              onOpenRule={onOpenRule}
              onNewer={selectedIndex > 0 ? () => select(visibleEntries[selectedIndex - 1], "replace") : undefined}
              onOlder={
                selectedIndex >= 0 && selectedIndex < visibleEntries.length - 1
                  ? () => select(visibleEntries[selectedIndex + 1], "replace")
                  : undefined
              }
            />
          )}
        </div>
      </section>
    </div>
  )
}

function ActivityHeading() {
  return (
    <div>
      <h1>What your rules did</h1>
      <p className="page-intro">
        Every event a rule added, updated, removed, skipped, or blocked, and why. Events are named as
        each run found them.
      </p>
    </div>
  )
}

function rulePickerOptions(
  ruleId: string,
  entries: AuditEntry[],
  context: RuleContext,
): { options: RulePickerOption[]; showAccounts: boolean } {
  const rules = [...context.rulesById.values()]
  const endpoint = (value: Rule["source"]) => ({
    calendar: endpointName(value, context),
    accountId: value.connected_account_id,
    account: context.accountsById.get(value.connected_account_id),
  })
  // History can name rules that were removed; they stay filterable.
  const removed = context.rulesLoaded
    ? [...new Set([...entries.map((item) => item.rule_id), ...(ruleId ? [ruleId] : [])])].filter(
        (id) => !context.rulesById.has(id),
      )
    : []
  const options: RulePickerOption[] = [
    { value: "", name: "All rules" },
    ...rules.map((rule) => {
      const source = endpoint(rule.source)
      const destination = endpoint(rule.destination)
      return { value: rule.id, name: `${source.calendar} to ${destination.calendar}`, source, destination }
    }),
    ...removed.map((id, index) => ({
      value: id,
      name: removed.length > 1 ? `Removed rule ${index + 1}` : "Removed rule",
      removed: true,
    })),
  ]
  // Calendar names alone cannot tell apart two calendars that share a name.
  const calendars = new Map<string, Set<string>>()
  for (const rule of rules) {
    for (const side of [rule.source, rule.destination]) {
      const name = endpointName(side, context)
      calendars.set(name, (calendars.get(name) ?? new Set()).add(`${side.connected_account_id}/${side.calendar_id}`))
    }
  }
  return { options, showAccounts: [...calendars.values()].some((ids) => ids.size > 1) }
}

function EmptyActivity({
  ruleId,
  show,
  query,
  onShowAll,
  onAllRules,
  onClearSearch,
}: {
  ruleId: string
  show: ActivityShow
  query: string
  onShowAll: () => void
  onAllRules: () => void
  onClearSearch: () => void
}) {
  // The default view hides no-change checks, so an empty page there is usually good news.
  const quiet = !ruleId && show === "" && !query
  const filtered = Boolean(ruleId) || show !== "all" || Boolean(query)
  return (
    <div className="empty-panel">
      <div className="empty-icon"><Activity aria-hidden="true" /></div>
      <h2>{quiet ? "Nothing has changed yet" : query ? `No events named “${query}”` : filtered ? "No matching activity" : "No activity yet"}</h2>
      <p>
        {quiet
          ? "No rule has added, updated, removed, skipped, or blocked an event. Checks that found everything already up to date are hidden."
          : query
            ? "Search matches event titles as each run recorded them. Check the spelling, show all decisions, or clear the search."
            : filtered
              ? "No recorded decisions match these filters. Show all decisions, or choose a different rule."
              : "Synchronization decisions will appear here after an enabled rule completes its first run."}
      </p>
      {filtered && (
        <div className="empty-actions">
          {query && <Button variant="outline" onClick={onClearSearch}>Clear search</Button>}
          {show !== "all" && <Button variant="outline" onClick={onShowAll}>Show all decisions</Button>}
          {ruleId && <Button variant="outline" onClick={onAllRules}>Show all rules</Button>}
        </div>
      )}
    </div>
  )
}

const SEARCH_DELAY_MS = 300

/**
 * Searches recorded event titles as the administrator types, pausing briefly so each keystroke
 * does not replace the table. Enter searches at once; Escape clears.
 */
function ActivitySearch({ query, onSearch }: { query: string; onSearch: (query: string) => void }) {
  const [text, setText] = useState(query)
  const [shownQuery, setShownQuery] = useState(query)
  const input = useRef<HTMLInputElement>(null)
  const search = useRef(onSearch)
  useEffect(() => {
    search.current = onSearch
  })
  // A search cleared elsewhere, such as from the empty state, empties the field too.
  if (query !== shownQuery) {
    setShownQuery(query)
    if (text.trim() !== query) setText(query)
  }

  useEffect(() => {
    if (text.trim() === query) return
    const timer = window.setTimeout(() => search.current(text.trim()), SEARCH_DELAY_MS)
    return () => window.clearTimeout(timer)
  }, [text, query])

  function clear() {
    setText("")
    onSearch("")
    input.current?.focus()
  }

  return (
    <div className="field-stack">
      <Label htmlFor="activity-search">Event</Label>
      <div className="activity-search">
        <Search aria-hidden="true" className="activity-search-icon" />
        <Input
          ref={input}
          id="activity-search"
          type="search"
          value={text}
          placeholder="Search event titles"
          autoComplete="off"
          spellCheck={false}
          maxLength={200}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault()
              if (text.trim() !== query) onSearch(text.trim())
            } else if (event.key === "Escape" && text) {
              event.preventDefault()
              clear()
            }
          }}
        />
        {text && (
          <button type="button" className="activity-search-clear" aria-label="Clear search" title="Clear search" onClick={clear}>
            <X aria-hidden="true" />
          </button>
        )}
      </div>
    </div>
  )
}

function EntryRow({
  entry,
  context,
  state,
  selected,
  showRuleColumn,
  onOpen,
  onFilterRule,
}: {
  entry: AuditEntry
  context: RuleContext
  state: ActivityLocationState
  selected: boolean
  showRuleColumn: boolean
  onOpen: (entry: AuditEntry) => void
  onFilterRule: (ruleId: string) => void
}) {
  const names = ruleNames(entry.rule_id, context)
  const cell = eventCell(entry, names)
  const href = `${window.location.pathname}${activitySearch({ ...state, entryId: entry.id })}`
  const follow = (event: MouseEvent<HTMLAnchorElement>) => {
    if (!isPlainLeftClick(event)) return
    event.preventDefault()
    onOpen(entry)
  }
  return (
    <tr
      role="row"
      className="activity-row"
      data-selected={selected}
      // The event link is the row's keyboard target; the rest of the row is a larger mouse target.
      onClick={(event) => {
        if (!(event.target as HTMLElement).closest("a, button")) onOpen(entry)
      }}
    >
      <td role="cell" className="activity-col-time">
        <time dateTime={entry.occurred_at}>{formatClockTime(entry.occurred_at)}</time>
        <span className="sr-only">, {formatDay(entry.occurred_at)}</span>
      </td>
      <td role="cell" className="activity-col-event">
        <a
          href={href}
          className="activity-row-link"
          data-row-link={entry.id}
          aria-current={selected ? "true" : undefined}
          onClick={follow}
        >
          <EventCellContent cell={cell} />
        </a>
      </td>
      <td role="cell" className="activity-col-happened">
        <HappenedLabel entry={entry} names={names} />
      </td>
      {showRuleColumn && (
        <td role="cell" className="activity-col-rule">
          <button
            type="button"
            className="activity-rule-name"
            onClick={() => onFilterRule(entry.rule_id)}
            aria-label={names ? `Show only ${names.source} to ${names.destination}` : "Show only this removed rule"}
          >
            {names ? (
              <>
                <span>{names.source}</span>
                <ArrowRight aria-hidden="true" />
                <span>{names.destination}</span>
              </>
            ) : (
              <span>Removed rule</span>
            )}
          </button>
        </td>
      )}
    </tr>
  )
}

function EventCellContent({ cell }: { cell: EventCell }) {
  if (cell.state === "unavailable") {
    return (
      <span className="activity-event-cell activity-event-cell-muted">
        <span className="activity-event-title">{cell.label}</span>
        {cell.note && <span className="activity-event-when">{cell.note}</span>}
      </span>
    )
  }
  return (
    <span className="activity-event-cell">
      <span className="activity-event-title">{cell.title}</span>
      <EventWhen cell={cell} />
    </span>
  )
}

function HappenedLabel({ entry, names }: { entry: AuditEntry; names: RuleNames | null }) {
  return <HappenedLine happened={whatHappened(entry, names)} />
}

function ActivityDetail({
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
  onNewer?: () => void
  onOlder?: () => void
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
  const cell = eventCell(entry, names)
  const copy = describeEntry(entry, names)
  const exists = names !== null
  const inspection = entryInspection(entry, exists)
  return (
    <>
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
      {inspection === "event" ? (
        <ActivityEventDetails entry={entry} />
      ) : (
        entry.source_event_id && <p className="activity-event-status">{REMOVED_RULE_LOOKUP}</p>
      )}
      <details className="activity-diagnostics">
        <summary>Technical details</summary>
        <dl>
          <Diagnostic label="Entry" value={String(entry.id)} />
          <Diagnostic label="Run" value={entry.run_id} />
          <Diagnostic label="Decision" value={[entry.action, entry.reason].filter(Boolean).join(" · ")} />
          <Diagnostic label="Source event ID" value={entry.source_event_id} />
          <Diagnostic label="Projection event ID" value={entry.destination_event_id} />
          {entry.detail && entry.detail !== copy.explanation && <Diagnostic label="Recorded detail" value={entry.detail} />}
        </dl>
      </details>
    </>
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

function incidentRuleState(incident: Incident, context: RuleContext): IncidentRuleState | null {
  if (!incident.rule_id) return null
  // Until rules load, assume the rule exists but claim no renewed access.
  if (!context.rulesLoaded) return { accountsConnected: false }
  const rule = context.rulesById.get(incident.rule_id)
  if (!rule) return null
  const connected = (accountId: string) => context.accountsById.get(accountId)?.state === "connected"
  return { accountsConnected: connected(rule.source.connected_account_id) && connected(rule.destination.connected_account_id) }
}

function IncidentRule({ incident, context }: { incident: Incident; context: RuleContext }) {
  return incident.rule_id ? <RuleDirection ruleId={incident.rule_id} context={context} /> : <span>Installation</span>
}

/** Only incidents that still need attention lead the page, each with its next step. */
function OpenIncidents({
  incidents,
  context,
  onAction,
}: {
  incidents: Incident[]
  context: RuleContext
  onAction: (action: IncidentAction) => void
}) {
  if (incidents.length === 0) return null
  return (
    <section className="workflow activity-section" aria-labelledby="incidents-title">
      <div className="section-heading">
        <div>
          <h2 id="incidents-title">Incidents</h2>
          <p>Each stays open until Calendar Sync confirms the problem is gone.</p>
        </div>
      </div>
      <ul className="rule-list">
        {incidents.map((incident) => {
          const { detail, action } = incidentGuidance(incident, incidentRuleState(incident, context))
          return (
            <li className="rule-row incident-row" key={incident.id}>
              <div className="incident-heading">
                <strong>{incident.summary}</strong>
                <Badge variant="attention">Open</Badge>
              </div>
              <div className="activity-run-meta">
                <IncidentRule incident={incident} context={context} />
                <span>Since {formatRunTime(incident.opened_at)}</span>
                {incident.updated_at !== incident.opened_at && <span>Last seen {formatRunTime(incident.updated_at)}</span>}
              </div>
              {detail && <p className="incident-detail">{detail}</p>}
              {action && (
                <div>
                  <Button variant="outline" size="sm" onClick={() => onAction(action)}>
                    {action.label}
                    <ArrowRight aria-hidden="true" />
                  </Button>
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

/** Resolved incidents are kept as evidence, out of the way until asked for. */
function ResolvedIncidents({ incidents, context }: { incidents: Incident[]; context: RuleContext }) {
  const [open, setOpen] = useState(false)
  if (incidents.length === 0) return null
  return (
    <section className="resolved-incidents" aria-label="Resolved incidents">
      <Button
        variant="ghost"
        size="sm"
        className="resolved-incidents-toggle"
        aria-expanded={open}
        aria-controls="resolved-incidents-list"
        onClick={() => setOpen((value) => !value)}
      >
        {open ? <ChevronUp aria-hidden="true" /> : <ChevronDown aria-hidden="true" />}
        {open ? "Hide resolved incidents" : `Show ${plural(incidents.length, "resolved incident")}`}
      </Button>
      {open && (
        <ul id="resolved-incidents-list" className="rule-list">
          {incidents.map((incident) => {
            const resolution = incidentResolution(incident)
            return (
              <li className="rule-row incident-row" key={incident.id}>
                <div className="incident-heading">
                  <strong>{incident.summary}</strong>
                  <Badge variant="neutral">Resolved</Badge>
                </div>
                <div className="activity-run-meta">
                  <IncidentRule incident={incident} context={context} />
                  <span>Opened {formatRunTime(incident.opened_at)}</span>
                  <span>Closed {formatRunTime(incidentClosedAt(incident))}</span>
                </div>
                {resolution && <p className="incident-detail">{resolution}</p>}
              </li>
            )
          })}
        </ul>
      )}
    </section>
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
  if (!rule) return <span className="activity-removed-rule">Removed rule</span>
  return (
    <span className="rule-direction activity-direction">
      <RuleEndpoint
        account={context.accountsById.get(rule.source.connected_account_id)}
        accountId={rule.source.connected_account_id}
        calendarId={rule.source.calendar_id}
        calendars={context.calendarsByAccount.get(rule.source.connected_account_id)}
        role="Source"
      />
      <ArrowRight aria-label="to" role="img" />
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
