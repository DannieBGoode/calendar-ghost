import {
  keepPreviousData,
  skipToken,
  useInfiniteQuery,
  useQueries,
  useQuery,
} from "@tanstack/react-query"
import { RefreshCw, ShieldAlert } from "lucide-react"
import { useEffect, useRef, useState, type RefObject } from "react"

import { PageSkeleton } from "@/components/page-skeleton"
import { PageTabs } from "@/components/page-tabs"
import { Button } from "@/components/ui/button"
import { HistorySection, type ActivityFeed, type UpdateLocation } from "@/features/activity-history"
import { IncidentsSection } from "@/features/activity-incidents"
import { useI18n } from "@/i18n/provider"
import { showCategories } from "@/lib/activity"
import {
  activityFailure,
  activityFailureActions,
  activityFailureMessages,
  activityFailureRequiresReload,
} from "@/lib/activity-failure"
import { activitySearch, activityStateFromSearch, type ActivityLocationState } from "@/lib/activity-location"
import type { RuleContext } from "@/lib/activity-rule-context"
import { ACTIVITY_PAGE_SIZE, api, type AuditEntry, type Incident } from "@/lib/api"
import { documentTitle } from "@/lib/brand"
import { openIncidentCount, type IncidentStep } from "@/lib/incidents"
import {
  accountSearch,
  appPathForActivityTab,
  appPathForIncident,
  DEFAULT_ACTIVITY_TAB,
  type ActivityTab,
  type OpenRule,
  type ViewChange,
} from "@/lib/navigation"

/** Opens a tab of Activity; History can open with its filters changed, such as to one rule's blocks. */
type OpenActivityTab = (tab: ActivityTab, filters?: Partial<ActivityLocationState>) => void
/** Opens one Incident beside the table, or closes it with null. */
type SelectIncident = (incidentId: string | null, history: "push" | "replace") => void

/**
 * Filters and the open entry live in the address so Back, reload, and shared links keep them. The
 * view remounts on every arrival, including Back and Forward, so it only reads the address once.
 * They belong to History, so every change opens History's own address.
 */
function useActivityLocation() {
  const [state, setState] = useState(() => activityStateFromSearch(window.location.search))

  function update(next: Partial<ActivityLocationState>, history: "push" | "replace") {
    const merged = { ...state, ...next }
    const url = `${appPathForActivityTab("history")}${activitySearch(merged)}`
    if (history === "push") window.history.pushState(null, "", url)
    else window.history.replaceState(null, "", url)
    setState(merged)
  }

  return [state, update] as const
}

/**
 * Which tab shows, and which Incident is open beside its table. Each has its own address; switching
 * keeps this page, and History's filters, in place.
 */
function useActivityTabs(
  initialTab: ActivityTab | undefined,
  initialIncidentId: string | undefined,
  update: UpdateLocation,
) {
  const i18n = useI18n()
  const [tab, setTab] = useState(initialTab ?? DEFAULT_ACTIVITY_TAB)
  const [incidentId, setIncidentId] = useState(initialIncidentId ?? null)
  useEffect(() => {
    const page = tab === "incidents" ? i18n.t("activity.tabs.documentTitle") : i18n.t("app.nav.activity")
    document.title = documentTitle(i18n, page)
  }, [i18n, tab])

  function openTab(next: ActivityTab, filters?: Partial<ActivityLocationState>) {
    if (next === tab && !filters) return
    if (next === "history") update(filters ?? {}, "push")
    else window.history.pushState(null, "", appPathForActivityTab(next))
    setTab(next)
    setIncidentId(null)
  }

  // Each Incident has its own address too, so Back closes it and a link opens it.
  function selectIncident(next: string | null, history: "push" | "replace") {
    const url = next === null ? appPathForActivityTab("incidents") : appPathForIncident(next)
    if (history === "push") window.history.pushState(null, "", url)
    else window.history.replaceState(null, "", url)
    setIncidentId(next)
  }

  return { tab, incidentId, openTab, selectIncident }
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

export function ActivityView({
  tab: initialTab,
  incidentId: initialIncidentId,
  onViewChange,
  onOpenRule,
}: {
  /** The tab the address names; History when it names none. */
  tab?: ActivityTab | undefined
  /** The Incident the address opens beside the Incidents table. */
  incidentId?: string | undefined
  onViewChange: ViewChange
  onOpenRule: OpenRule
}) {
  const i18n = useI18n()
  const { t } = i18n
  const [state, update] = useActivityLocation()
  const { tab, incidentId, openTab, selectIncident } = useActivityTabs(initialTab, initialIncidentId, update)
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
      tab={tab}
      onOpenTab={openTab}
      incidentId={incidentId}
      onSelectIncident={selectIncident}
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
  tab,
  onOpenTab,
  incidentId,
  onSelectIncident,
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
  tab: ActivityTab
  onOpenTab: OpenActivityTab
  incidentId: string | null
  onSelectIncident: SelectIncident
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
  function showHistory(ruleId: string, show: "blocked" | "") {
    onOpenTab("history", { ruleId, show, query: "", entryId: null })
    requestAnimationFrame(() => document.getElementById("activity-feed-title")?.scrollIntoView({ block: "start" }))
  }

  // Every kind of step is handled here; a new one fails to compile until it is.
  function followStep(step: IncidentStep) {
    switch (step.kind) {
      case "settings": {
        const search = step.accountId ? { search: accountSearch(step.accountId) } : {}
        onViewChange("settings", { settingsTab: "connections", ...search })
        return
      }
      case "rule":
        onOpenRule(step.ruleId)
        return
      case "blocked":
        showHistory(step.ruleId, "blocked")
        return
      case "history":
        showHistory(step.ruleId, "")
        return
      default: {
        const unhandled: never = step
        return unhandled
      }
    }
  }

  return (
    <div className="page-section">
      <ActivityHeading tab={tab} />
      {/* Without any Incident there is only History, so Activity needs no tabs. */}
      {(incidents.length > 0 || tab === "incidents") && (
        <ActivityTabs current={tab} openCount={openIncidentCount(incidents)} onOpen={onOpenTab} />
      )}
      {tab === "incidents" ? (
        <IncidentsSection
          incidents={incidents}
          selectedId={incidentId}
          context={context}
          onSelect={onSelectIncident}
          onStep={followStep}
        />
      ) : (
        <HistorySection
          state={state}
          query={query}
          update={update}
          feed={feed}
          entries={entries}
          context={context}
          selection={selection}
          focusDetailRef={focusDetailRef}
          onOpenRule={onOpenRule}
        />
      )}
    </div>
  )
}

function ActivityTabs({
  current,
  openCount,
  onOpen,
}: {
  current: ActivityTab
  openCount: number
  onOpen: (tab: ActivityTab) => void
}) {
  const { t } = useI18n()
  return (
    <PageTabs
      label={t("activity.tabs.label")}
      current={current}
      onOpen={onOpen}
      tabs={[
        { id: "history", label: t("activity.tabs.history"), href: appPathForActivityTab("history") },
        {
          id: "incidents",
          label: t("activity.tabs.incidents"),
          href: appPathForActivityTab("incidents"),
          count: openCount,
          countLabel: t("activity.tabs.openCount", { count: openCount }),
          countTone: "attention",
        },
      ]}
    />
  )
}

/** The page names what its tab shows: what the rules did, or what needed attention. */
function ActivityHeading({ tab = "history" }: { tab?: ActivityTab }) {
  const { t } = useI18n()
  return (
    <div>
      <h1>{tab === "incidents" ? t("activity.page.incidentsTitle") : t("activity.page.title")}</h1>
      <p className="page-intro">{tab === "incidents" ? t("activity.page.incidentsIntro") : t("activity.page.intro")}</p>
    </div>
  )
}
