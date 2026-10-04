import {
  keepPreviousData,
  skipToken,
  useInfiniteQuery,
  useQueries,
  useQuery,
  type InfiniteData,
  type UseInfiniteQueryResult,
} from "@tanstack/react-query"
import { RefreshCw, ShieldAlert } from "lucide-react"
import { useRef, useState, type RefObject } from "react"

import { GhostMark } from "@/components/ghost-mark"
import { PageSkeleton } from "@/components/page-skeleton"
import { Button } from "@/components/ui/button"
import { ActivityDetail } from "@/features/activity-entry-details"
import { ActivityFilters } from "@/features/activity-filters"
import { OpenIncidents, ResolvedIncidents } from "@/features/activity-incidents"
import { ActivityTable } from "@/features/activity-table"
import { useI18n } from "@/i18n/provider"
import { activityDayGroups, activityRows, groupRuns, showCategories } from "@/lib/activity"
import {
  activityFailure,
  activityFailureActions,
  activityFailureMessages,
  activityFailureRequiresReload,
} from "@/lib/activity-failure"
import { emptyHistoryCopy, entrySteps, historyStatus, type HistoryFilters } from "@/lib/activity-history"
import { activitySearch, activityStateFromSearch, type ActivityLocationState } from "@/lib/activity-location"
import type { RuleContext } from "@/lib/activity-rule-context"
import { ACTIVITY_PAGE_SIZE, api, type AuditEntry, type Incident } from "@/lib/api"
import { splitIncidents, type IncidentAction } from "@/lib/incidents"
import type { OpenRule, ViewChange } from "@/lib/navigation"

type UpdateLocation = (next: Partial<ActivityLocationState>, history: "push" | "replace") => void
type ActivityFeed = UseInfiniteQueryResult<InfiniteData<AuditEntry[]>>

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

/** The rules, accounts, and calendar names each entry needs to name its rule. */
function useRuleContext(): RuleContext {
  const i18n = useI18n()
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
  return {
    rulesById: new Map((rules.data ?? []).map((rule) => [rule.id, rule])),
    accountsById: new Map((accounts.data ?? []).map((account) => [account.id, account])),
    calendarsByAccount: new Map(
      connectedAccountIds.map((accountId, index) => [accountId, calendarQueries[index]?.data]),
    ),
    rulesLoaded: rules.data !== undefined,
    i18n,
  }
}

/** The open entry, from the loaded pages or, when they do not hold it, on its own. */
function useSelectedEntry(entryId: number | null, entries: AuditEntry[], feedPending: boolean) {
  const listedEntry = entries.find((item) => item.id === entryId)
  // A shared link or an older page can name an entry that is not loaded.
  const directEntry = useQuery({
    queryKey: ["activity-entry", entryId],
    queryFn: entryId === null ? skipToken : () => api.activityEntry(entryId),
    enabled: listedEntry === undefined && !feedPending,
    retry: false,
  })
  const entry = listedEntry ?? (directEntry.data?.id === entryId ? directEntry.data : undefined)
  return { entry, loading: entry === undefined && (directEntry.isPending || directEntry.isFetching) }
}

export function ActivityView({ onViewChange, onOpenRule }: { onViewChange: ViewChange; onOpenRule: OpenRule }) {
  const { t } = useI18n()
  const [state, update] = useActivityLocation()
  const { ruleId, show, entryId } = state
  const query = state.query ?? ""
  const focusDetail = useRef(false)
  const activity = useInfiniteQuery({
    queryKey: ["activity", ruleId, show, query],
    queryFn: ({ pageParam }) => api.activity({
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
  const context = useRuleContext()
  const entries = activity.data?.pages.flat() ?? []
  const selection = useSelectedEntry(entryId, entries, activity.isPending)

  if (activity.isPending || incidents.isPending) return <PageSkeleton label={t("activity.page.loading")} />

  if (activity.error || incidents.error) {
    return (
      <ActivityUnavailable
        errors={[activity.error, incidents.error]}
        refreshing={activity.isFetching || incidents.isFetching}
        onRetry={() => void Promise.all([activity.refetch(), incidents.refetch()])}
      />
    )
  }

  return (
    <ActivityPage
      state={state}
      query={query}
      update={update}
      feed={activity}
      entries={entries}
      incidents={incidents.data}
      context={context}
      selection={selection}
      focusDetailRef={focusDetail}
      onViewChange={onViewChange}
      onOpenRule={onOpenRule}
    />
  )
}

function ActivityUnavailable({
  errors,
  refreshing,
  onRetry,
}: {
  errors: unknown[]
  refreshing: boolean
  onRetry: () => void
}) {
  const { t } = useI18n()
  const failure = activityFailure(errors)
  const reloadRequired = activityFailureRequiresReload(failure)
  const recover = () => {
    if (reloadRequired) {
      window.location.reload()
      return
    }
    onRetry()
  }

  return (
    <div className="page-section">
      <ActivityHeading />
      <section className="empty-panel" role="alert" aria-labelledby="activity-error-title">
        <div className="empty-icon empty-icon-error"><ShieldAlert aria-hidden="true" /></div>
        <h2 id="activity-error-title">{t("activity.failure.title")}</h2>
        <p>{t(activityFailureMessages[failure])}</p>
        <Button variant="outline" onClick={recover} disabled={refreshing && !reloadRequired}>
          <RefreshCw aria-hidden="true" />
          {refreshing && !reloadRequired ? t("activity.failure.retrying") : t(activityFailureActions[failure])}
        </Button>
      </section>
    </div>
  )
}

function ActivityPage({
  state,
  query,
  update,
  feed,
  entries,
  incidents,
  context,
  selection,
  focusDetailRef,
  onViewChange,
  onOpenRule,
}: {
  state: ActivityLocationState
  query: string
  update: UpdateLocation
  feed: ActivityFeed
  entries: AuditEntry[]
  incidents: Incident[]
  context: RuleContext
  selection: { entry: AuditEntry | undefined; loading: boolean }
  focusDetailRef: RefObject<boolean>
  onViewChange: ViewChange
  onOpenRule: OpenRule
}) {
  const i18n = useI18n()
  const { t } = i18n
  const { ruleId, show, entryId } = state
  const { open: openIncidents, resolved: resolvedIncidents } = splitIncidents(incidents)
  const runs = groupRuns(entries)
  const groups = activityRows(i18n, runs)
  const days = activityDayGroups(groups)
  const visibleEntries = runs.flatMap((run) => run.entries)
  const { newer, older } = entrySteps(visibleEntries, selection.entry)
  const updating = feed.isPlaceholderData
  const detailOpen = entryId !== null

  function select(entry: AuditEntry | undefined, history: "push" | "replace") {
    if (entry) update({ entryId: entry.id }, history)
  }

  function openEntry(entry: AuditEntry) {
    focusDetailRef.current = true
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

  function stepTo(rowLink: string | undefined) {
    // With details open, the arrow keys step through entries without leaving the table.
    if (detailOpen) select(visibleEntries.find((item) => String(item.id) === rowLink), "replace")
  }

  // A selected rule is named above the table, and the detail pane names the rule of its entry.
  const showRuleColumn = !ruleId && !detailOpen

  return (
    <div className="page-section">
      <ActivityHeading />
      <OpenIncidents incidents={openIncidents} context={context} onAction={followIncident} />
      <ResolvedIncidents incidents={resolvedIncidents} context={context} />

      <section className="workflow activity-section page-card" aria-labelledby="activity-feed-title">
        <div className="section-heading activity-feed-heading">
          <div>
            <h2 id="activity-feed-title">{t("activity.history.title")}</h2>
            <p>{t("activity.history.intro")}</p>
          </div>
        </div>
        <ActivityFilters
          query={query}
          ruleId={ruleId}
          show={show}
          entries={entries}
          context={context}
          onChange={changeFilters}
        />
        <p className="sr-only" role="status">
          {historyStatus(i18n, { updating, query, more: feed.hasNextPage, count: visibleEntries.length })}
        </p>

        {/* A linked entry the filters hide still opens beside an empty table. */}
        <div className="activity-layout" data-detail={detailOpen}>
          <div className="activity-table-wrap" aria-busy={updating} data-updating={updating}>
            {groups.length === 0 ? (
              <EmptyActivity
                filters={{ ruleId, show, query }}
                onShowAll={() => changeFilters({ show: "all" })}
                onAllRules={() => changeFilters({ ruleId: "" })}
                onClearSearch={() => changeFilters({ query: "" })}
              />
            ) : (
              <>
                <ActivityTable
                  days={days}
                  context={context}
                  state={state}
                  showRuleColumn={showRuleColumn}
                  onOpen={openEntry}
                  onFilterRule={(value) => changeFilters({ ruleId: value })}
                  onStep={stepTo}
                />
                {feed.hasNextPage && (
                  <Button variant="outline" className="activity-more" onClick={() => void feed.fetchNextPage()} disabled={feed.isFetchingNextPage}>
                    {feed.isFetchingNextPage ? t("activity.history.loadingOlder") : t("activity.history.loadOlder")}
                  </Button>
                )}
              </>
            )}
          </div>
          {detailOpen && (
            <ActivityDetail
              entry={selection.entry}
              loading={selection.loading}
              context={context}
              focusRef={focusDetailRef}
              onClose={closeDetail}
              onOpenRule={onOpenRule}
              onNewer={newer && (() => select(newer, "replace"))}
              onOlder={older && (() => select(older, "replace"))}
            />
          )}
        </div>
      </section>
    </div>
  )
}

function ActivityHeading() {
  const { t } = useI18n()
  return (
    <div>
      <h1>{t("activity.page.title")}</h1>
      <p className="page-intro">{t("activity.page.intro")}</p>
    </div>
  )
}

function EmptyActivity({
  filters,
  onShowAll,
  onAllRules,
  onClearSearch,
}: {
  filters: HistoryFilters
  onShowAll: () => void
  onAllRules: () => void
  onClearSearch: () => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  const { ruleId, show, query } = filters
  const copy = emptyHistoryCopy(i18n, filters)
  const filtered = Boolean(ruleId) || show !== "all" || Boolean(query)
  return (
    <div className="empty-panel">
      <GhostMark className="empty-ghost" />
      <h2>{copy.title}</h2>
      <p>{copy.body}</p>
      {filtered && (
        <div className="empty-actions">
          {query && <Button variant="outline" onClick={onClearSearch}>{t("activity.search.clear")}</Button>}
          {show !== "all" && <Button variant="outline" onClick={onShowAll}>{t("activity.filters.showAll")}</Button>}
          {ruleId && <Button variant="outline" onClick={onAllRules}>{t("activity.filters.showAllRules")}</Button>}
        </div>
      )}
    </div>
  )
}
