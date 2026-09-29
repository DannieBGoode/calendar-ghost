import { keepPreviousData, useInfiniteQuery, useQueries, useQuery } from "@tanstack/react-query"
import {
  Activity,
  ArrowRight,
  Check,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  RefreshCw,
  Repeat,
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
  type ActivityGroup,
  type ActivityRow,
  type EventCell,
  type ExpandedChecks,
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
  type Rule,
} from "@/lib/api"
import { isPlainLeftClick, type OpenRule } from "@/lib/navigation"
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


export function ActivityView({ onOpenRule }: { onOpenRule: OpenRule }) {
  const [state, update] = useActivityLocation()
  const { ruleId, show, entryId } = state
  // Expanded runs and how many pages of their no-change checks are loaded.
  const [expandedRuns, setExpandedRuns] = useState<ReadonlyMap<string, number>>(new Map())
  const focusDetail = useRef(false)
  const activity = useInfiniteQuery({
    queryKey: ["activity", ruleId, show],
    queryFn: ({ pageParam }) =>
      api.activity({ ruleId: ruleId || undefined, categories: showCategories(show), before: pageParam }),
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
  // The default view hides no-change checks; each run still says how many it made, including runs
  // that made nothing else. Runs older than the loaded entries wait until older entries load.
  const countsNoChange = show === ""
  const oldestLoaded = entries.at(-1)?.id
  const noChangeAfter = activity.hasNextPage && oldestLoaded ? oldestLoaded - 1 : 0
  const noChangeRuns = useQuery({
    queryKey: ["activity-no-change-runs", ruleId, noChangeAfter],
    queryFn: () => api.noChangeRuns({ ruleId: ruleId || undefined, after: noChangeAfter }),
    enabled: countsNoChange && !activity.isPending,
    placeholderData: keepPreviousData,
  })
  const listedEntry = entries.find((item) => item.id === entryId)
  // A shared link or an older page can name an entry that is not loaded.
  const directEntry = useQuery({
    queryKey: ["activity-entry", entryId],
    queryFn: () => api.activityEntry(entryId as number),
    enabled: entryId !== null && listedEntry === undefined && !activity.isPending,
    retry: false,
  })
  const selected = listedEntry ?? (directEntry.data?.id === entryId ? directEntry.data : undefined)
  // An open no-change check shows in the table by expanding its run.
  const openRun = countsNoChange && selected?.category === "unchanged" ? selected.run_id : null
  const expanded: [string, number][] = [
    ...expandedRuns,
    ...(openRun && !expandedRuns.has(openRun) ? [[openRun, 1] as [string, number]] : []),
  ]
  const expandedChecks = useQueries({
    queries: expanded.map(([runKey, pages]) => ({
      queryKey: ["activity-no-change-checks", runKey, pages],
      queryFn: () => loadNoChangeChecks(runKey, pages),
      enabled: countsNoChange,
      placeholderData: keepPreviousData,
    })),
  })
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
  const loadedChecks = new Map<string, ExpandedChecks>()
  const loadingRuns = new Set<string>()
  expanded.forEach(([runKey], index) => {
    const query = expandedChecks[index]
    if (query?.data) loadedChecks.set(runKey, query.data)
    if (!query?.data || query.isPlaceholderData) loadingRuns.add(runKey)
  })
  const groups = activityRows(runs, {
    noChangeRuns: countsNoChange ? noChangeRuns.data : undefined,
    expanded: loadedChecks,
  })
  const visibleEntries = groups.flatMap((group) =>
    group.kind === "run" ? group.rows.flatMap((row) => (row.kind === "entry" ? [row.entry] : [])) : [],
  )
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
    setExpandedRuns(new Map())
    update({ ...next, entryId: null }, "replace")
  }

  function toggleRun(runKey: string) {
    setExpandedRuns((current) => {
      const next = new Map(current)
      if (!next.delete(runKey)) next.set(runKey, 1)
      return next
    })
  }

  function loadMoreChecks(runKey: string) {
    setExpandedRuns((current) => new Map(current).set(runKey, (current.get(runKey) ?? 1) + 1))
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
      {incidents.data.length > 0 && (
        <section className="workflow activity-section">
          <div className="section-heading"><div><h2>Incidents</h2><p>Authorization problems, repeated provider failures, and events still blocked at the daily check.</p></div></div>
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

      <section className="workflow activity-section" aria-labelledby="activity-feed-title">
        <div className="section-heading activity-feed-heading">
          <div>
            <h2 id="activity-feed-title">History</h2>
            <p>Newest first. Select an entry to see what happened and why.</p>
          </div>
          <div className="activity-filters">
            <div className="field-stack">
              <Label id="activity-rule-label" onClick={() => document.getElementById("activity-rule")?.focus()}>Rule</Label>
              <RulePicker
                id="activity-rule"
                labelId="activity-rule-label"
                value={ruleId}
                options={pickerOptions.options}
                showAccounts={pickerOptions.showAccounts}
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
        </div>
        <p className="sr-only" role="status">{updating ? "Updating activity…" : ""}</p>

        {groups.length === 0 ? (
          <EmptyActivity
            ruleId={ruleId}
            show={show}
            onShowAll={() => changeFilters({ show: "all" })}
            onAllRules={() => changeFilters({ ruleId: "" })}
          />
        ) : (
          <div className="activity-layout" data-detail={detailOpen}>
            <div className="activity-table-wrap" aria-busy={updating} data-updating={updating}>
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
                    {group.kind === "quiet" ? (
                      <QuietRunsRow group={group} columns={columns} onShowAll={() => changeFilters({ show: "all" })} />
                    ) : (
                      group.rows.map((row) => (
                        <ActivityTableRow
                          key={row.kind === "entry" ? row.entry.id : `${group.key}-folded`}
                          row={row}
                          loadingChecks={row.kind === "folded" && loadingRuns.has(group.key)}
                          context={context}
                          state={state}
                          selectedId={entryId}
                          showRuleColumn={showRuleColumn}
                          onOpen={openEntry}
                          onFilterRule={(value) => changeFilters({ ruleId: value })}
                          onToggleRun={() => toggleRun(group.key)}
                          onLoadMore={() => loadMoreChecks(group.key)}
                        />
                      ))
                    )}
                  </tbody>,
                ])}
              </table>
              {activity.hasNextPage && (
                <Button variant="outline" className="activity-more" onClick={() => activity.fetchNextPage()} disabled={activity.isFetchingNextPage}>
                  {activity.isFetchingNextPage ? "Loading older activity…" : "Load older activity"}
                </Button>
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
        )}
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
  onShowAll,
  onAllRules,
}: {
  ruleId: string
  show: ActivityShow
  onShowAll: () => void
  onAllRules: () => void
}) {
  // The default view hides no-change checks, so an empty page there is usually good news.
  const quiet = !ruleId && show === ""
  const filtered = Boolean(ruleId) || show !== "all"
  return (
    <div className="empty-panel">
      <div className="empty-icon"><Activity aria-hidden="true" /></div>
      <h2>{quiet ? "Nothing has changed yet" : filtered ? "No matching activity" : "No activity yet"}</h2>
      <p>
        {quiet
          ? "No rule has added, updated, removed, skipped, or blocked an event. Checks that found everything already up to date are hidden."
          : filtered
            ? "No recorded decisions match these filters. Show all decisions, or choose a different rule."
            : "Synchronization decisions will appear here after an enabled rule completes its first run."}
      </p>
      {filtered && (
        <div className="empty-actions">
          {show !== "all" && <Button variant="outline" onClick={onShowAll}>Show all decisions</Button>}
          {ruleId && <Button variant="outline" onClick={onAllRules}>Show all rules</Button>}
        </div>
      )}
    </div>
  )
}

function ActivityTableRow({
  row,
  loadingChecks,
  context,
  state,
  selectedId,
  showRuleColumn,
  onOpen,
  onFilterRule,
  onToggleRun,
  onLoadMore,
}: {
  row: ActivityRow
  loadingChecks: boolean
  context: RuleContext
  state: ActivityLocationState
  selectedId: number | null
  showRuleColumn: boolean
  onOpen: (entry: AuditEntry) => void
  onFilterRule: (ruleId: string) => void
  onToggleRun: () => void
  onLoadMore: () => void
}) {
  const toggleRef = useRef<HTMLButtonElement>(null)
  if (row.kind === "folded") {
    const label = row.expanded
      ? `Hide ${row.count} no-change ${row.count === 1 ? "check" : "checks"}`
      : `${row.count} ${row.count === 1 ? "event" : "events"} already up to date`
    return (
      <tr role="row" className="activity-folded-row">
        <td role="cell" className="activity-col-time" />
        <td role="cell" colSpan={showRuleColumn ? 3 : 2}>
          <div className="activity-fold-actions">
            <button
              ref={toggleRef}
              type="button"
              className="activity-fold"
              aria-expanded={row.expanded}
              onClick={onToggleRun}
            >
              <Check aria-hidden="true" />
              {label}
              <ChevronDown aria-hidden="true" data-open={row.expanded} />
            </button>
            {/* Show more goes away once every check is loaded, so focus moves to the fold toggle
                beside it first and is never lost; the status says what is loading. */}
            {row.more && (
              <button
                type="button"
                className="activity-fold"
                aria-disabled={loadingChecks || undefined}
                onClick={() => {
                  if (loadingChecks) return
                  toggleRef.current?.focus()
                  onLoadMore()
                }}
              >
                Show more
              </button>
            )}
            <span className="activity-fold-status" role="status">
              {loadingChecks ? "Loading…" : ""}
            </span>
          </div>
        </td>
      </tr>
    )
  }
  return (
    <EntryRow
      entry={row.entry}
      context={context}
      state={state}
      selected={selectedId === row.entry.id}
      showRuleColumn={showRuleColumn}
      onOpen={onOpen}
      onFilterRule={onFilterRule}
    />
  )
}

function QuietRunsRow({
  group,
  columns,
  onShowAll,
}: {
  group: Extract<ActivityGroup, { kind: "quiet" }>
  columns: number
  onShowAll: () => void
}) {
  const events = `${group.checks} ${group.checks === 1 ? "event" : "events"} already up to date`
  const scope = group.runs > 1 ? ` across ${group.runs} runs since ${formatClockTime(group.oldest)}` : ""
  return (
    <tr role="row" className="activity-folded-row activity-quiet-row">
      <td role="cell" className="activity-col-time">
        <time dateTime={group.newest}>{formatClockTime(group.newest)}</time>
      </td>
      <td role="cell" colSpan={columns - 1}>
        <div className="activity-fold-actions">
          <span className="activity-quiet"><Check aria-hidden="true" />{events}{scope}</span>
          <button type="button" className="activity-fold" onClick={onShowAll}>
            Show all decisions
          </button>
        </div>
      </td>
    </tr>
  )
}

/** Loads the first `pages` pages of one run's no-change checks. */
async function loadNoChangeChecks(runId: string, pages: number): Promise<ExpandedChecks> {
  const entries: AuditEntry[] = []
  let before: number | undefined
  for (let page = 0; page < pages; page += 1) {
    const batch = await api.activity({ runId, categories: ["unchanged"], before })
    entries.push(...batch)
    if (batch.length < ACTIVITY_PAGE_SIZE) return { entries, complete: true }
    before = batch.at(-1)?.id
  }
  return { entries, complete: false }
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
