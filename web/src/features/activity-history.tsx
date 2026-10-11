import type { InfiniteData, UseInfiniteQueryResult } from "@tanstack/react-query"
import type { RefObject } from "react"

import { GhostMark } from "@/components/ghost-mark"
import { Button } from "@/components/ui/button"
import { ActivityDetail } from "@/features/activity-entry-details"
import { ActivityFilters } from "@/features/activity-filters"
import { ActivityTable } from "@/features/activity-table"
import { useI18n } from "@/i18n/provider"
import { activityDayGroups, activityRows, groupRuns } from "@/lib/activity"
import { emptyHistoryCopy, entrySteps, historyStatus, type HistoryFilters } from "@/lib/activity-history"
import type { ActivityLocationState } from "@/lib/activity-location"
import type { RuleContext } from "@/lib/activity-rule-context"
import type { AuditEntry } from "@/lib/api"
import type { OpenRule } from "@/lib/navigation"

/** Changes History's filters or open entry, and its address with them. */
export type UpdateLocation = (next: Partial<ActivityLocationState>, history: "push" | "replace") => void
export type ActivityFeed = UseInfiniteQueryResult<InfiniteData<AuditEntry[]>>

/**
 * History, Activity's first tab: what each run did, filtered by rule, outcome, and title, with one
 * entry open beside the table.
 */
export function HistorySection({
  state,
  query,
  update,
  feed,
  entries,
  context,
  selection,
  focusDetailRef,
  onOpenRule,
}: {
  state: ActivityLocationState
  query: string
  update: UpdateLocation
  feed: ActivityFeed
  entries: AuditEntry[]
  context: RuleContext
  selection: { entry: AuditEntry | undefined; loading: boolean }
  focusDetailRef: RefObject<boolean>
  onOpenRule: OpenRule
}) {
  const i18n = useI18n()
  const { t } = i18n
  const { ruleId, show, entryId } = state
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

  function stepTo(rowLink: string | undefined) {
    // With details open, the arrow keys step through entries without leaving the table.
    if (detailOpen) select(visibleEntries.find((item) => String(item.id) === rowLink), "replace")
  }

  // A selected rule is named above the table, and the detail pane names the rule of its entry.
  const showRuleColumn = !ruleId && !detailOpen

  return (
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
