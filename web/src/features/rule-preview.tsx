import { useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowRight, Eye, Lock } from "lucide-react"
import { useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react"

import { PageSkeleton } from "@/components/page-skeleton"
import { LiveAnnouncement } from "@/components/rule-commands"
import { Button } from "@/components/ui/button"
import { PreviewFilterBar } from "@/features/rule-preview-filters"
import { PreviewFooter } from "@/features/rule-preview-footer"
import { PreviewEmpty, PreviewFailurePanel, PreviewReading, PreviewSkeleton } from "@/features/rule-preview-states"
import { PreviewAccounts, PreviewSettings } from "@/features/rule-preview-rule"
import { PreviewTable } from "@/features/rule-preview-table"
import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import { ApiError, api, type ConnectedAccount, type RuleDetail } from "@/lib/api"
import { documentTitle } from "@/lib/brand"
import { type OpenRule, type ViewChange } from "@/lib/navigation"
import { ruleEndpointLabel } from "@/lib/rule-endpoint"
import {
  isToday,
  layOut,
  NO_FILTERS,
  isFiltered,
  matchesFilters,
  narrowLayout,
  newSeries,
  type PreviewNames,
  type PreviewRun,
  previewSettings,
  type PreviewFilters,
} from "@/lib/rule-preview"
import { previewFailure } from "@/lib/rule-preview-failure"
import { RULE_CHANGE_QUERIES, rulePreviewKey } from "@/lib/use-rule-commands"
import { useRuleCalendars, type CalendarsByAccount } from "@/lib/use-rule-calendars"

type Names = PreviewNames

/**
 * The preview runs once per visit and is kept for the session; Refresh runs it anew. It waits for
 * the rule, so each run records the settings it was made with.
 */
function useRulePreview(ruleId: string, settings: string | null) {
  const queryClient = useQueryClient()
  return useQuery({
    queryKey: rulePreviewKey(ruleId),
    enabled: settings !== null,
    queryFn: async (): Promise<PreviewRun> => {
      try {
        const result = await api.previewRule(ruleId)
        return { items: result.items, completedAt: new Date(), settings: settings ?? "" }
      } finally {
        // A preview validates the rule, and a lapsed account it meets changes Settings too.
        void Promise.all(
          [...RULE_CHANGE_QUERIES, ["rule", ruleId]].map((queryKey) => queryClient.invalidateQueries({ queryKey })),
        )
      }
    },
    // A preview reads both calendars, so it runs only when asked: on opening, or Preview again.
    retry: false,
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: Number.POSITIVE_INFINITY,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })
}

function useNames(detail: RuleDetail, accounts: ConnectedAccount[], calendarsByAccount: CalendarsByAccount): Names {
  const i18n = useI18n()
  const name = (endpoint: RuleDetail["source"]) =>
    ruleEndpointLabel(
      i18n,
      endpoint,
      accounts.find((account) => account.id === endpoint.connected_account_id),
      calendarsByAccount.get(endpoint.connected_account_id),
    ).calendar
  return { source: name(detail.source), destination: name(detail.destination) }
}

export function RulePreviewView({
  ruleId,
  onViewChange,
  onOpenRule,
}: {
  ruleId: string
  onViewChange: ViewChange
  onOpenRule: OpenRule
}) {
  const { t } = useI18n()
  const rule = useQuery({ queryKey: ["rule", ruleId], queryFn: () => api.rule(ruleId), retry: false })
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: api.accounts })
  const preview = useRulePreview(ruleId, rule.data ? previewSettings(rule.data) : null)
  const { calendarsByAccount, namesReady } = useRuleCalendars(rule.data, accounts.data)
  const heading = useRef<HTMLHeadingElement>(null)
  const ready = Boolean(rule.data) && namesReady
  useEffect(() => {
    if (ready) heading.current?.focus()
  }, [ready])

  if (rule.isPending || accounts.isPending) return <PageSkeleton label={t("ruleDetails.page.loading")} />
  if (!rule.data || !accounts.data) {
    const missing = rule.error instanceof ApiError && rule.error.status === 404
    return (
      <section className="page-section" role="alert">
        <h1>{missing ? t("ruleDetails.page.missingTitle") : t("ruleDetails.page.loadFailedTitle")}</h1>
        <p className="page-intro">{missing ? t("ruleDetails.page.missingBody") : t("ruleDetails.page.loadFailedBody")}</p>
      </section>
    )
  }
  return (
    <RulePreviewPage
      detail={rule.data}
      accounts={accounts.data}
      calendarsByAccount={calendarsByAccount}
      preview={preview}
      heading={heading}
      onViewChange={onViewChange}
      onOpenRule={onOpenRule}
    />
  )
}

function RulePreviewPage({
  detail,
  accounts,
  calendarsByAccount,
  preview,
  heading,
  onViewChange,
  onOpenRule,
}: {
  detail: RuleDetail
  accounts: ConnectedAccount[]
  calendarsByAccount: CalendarsByAccount
  preview: ReturnType<typeof useRulePreview>
  heading: RefObject<HTMLHeadingElement | null>
  onViewChange: ViewChange
  onOpenRule: OpenRule
}) {
  const i18n = useI18n()
  const names = useNames(detail, accounts, calendarsByAccount)
  const [announcement, setAnnouncement] = useState("")
  // Kept here, not in the results, so a refresh does not throw the reader's filters away.
  const [filters, setFilters] = useState<PreviewFilters>(NO_FILTERS)
  // Another tab may change the rule; its refetched settings then no longer match this preview's.
  const outdated = preview.data !== undefined && preview.data.settings !== previewSettings(detail)
  // A failed refresh keeps the last data in the query; its numbers no longer stand, nor do an
  // outdated preview's.
  const run = preview.isFetching || preview.error || outdated ? undefined : preview.data
  // A failure stays on screen while Refresh retries it, so its own button keeps focus meaningful.
  const failure = preview.error
    ? previewFailure(i18n, preview.error, {
        ruleState: detail.state,
        ruleAccounts: [detail.source.connected_account_id, detail.destination.connected_account_id],
        accounts,
      })
    : null
  const refresh = useRef<HTMLButtonElement>(null)
  // A preview of settings the rule no longer has is read again at once, never started from.
  // A failure stops it there: its panel offers Refresh rather than a loop of failing reads.
  const { isFetching, isError, refetch } = preview
  useEffect(() => {
    if (outdated && !isFetching && !isError) void refetch()
  }, [outdated, isFetching, isError, refetch])
  // Refines the shell's "Preview" with the rule, so tabs and history tell previews apart.
  useEffect(() => {
    document.title = documentTitle(i18n, i18n.t("rulePreview.page.documentTitleRule", names))
  }, [i18n, names])
  // Focus moves to the lead's Refresh, which stays while reading, so a retry from a panel or the
  // footer, which then leave, never drops it to the page; the announcements say what happened.
  const retry = () => {
    refresh.current?.focus()
    setAnnouncement(readingText(i18n, detail, names))
    void preview.refetch().then((result) => {
      // The failure panel may be the same one as before, which a screen reader would not read again.
      if (result.error) setAnnouncement(i18n.t("rulePreview.states.failedTitle"))
      else if (result.data) setAnnouncement(leadText(i18n, result.data))
    })
  }
  const openRule = () => onOpenRule(detail.id)
  return (
    <div className="page-section rule-preview-page">
      <LiveAnnouncement text={announcement} />
      <PreviewHeader
        heading={heading}
        detail={detail}
        names={names}
        accounts={<PreviewAccounts detail={detail} accounts={accounts} />}
        lead={<PreviewLead run={run} reading={preview.isFetching} refreshRef={refresh} onRetry={retry} />}
        settings={<PreviewSettings detail={detail} onChange={openRule} />}
      />
      {/* Above whatever waits on the read: the first rows, a failure being retried, or the last
          results, dimmed, so the reader sees it is moving on in the place they are looking. */}
      {preview.isFetching && <PreviewReading text={readingText(i18n, detail, names)} />}
      {failure ? (
        <PreviewFailurePanel failure={failure} ruleId={detail.id} busy={preview.isFetching} onRetry={retry} onOpenRule={openRule} onViewChange={onViewChange} />
      ) : preview.data ? (
        // While Refresh reads, the last results stay, dimmed, so the reader keeps their place.
        <PreviewResults
          run={preview.data}
          busy={preview.isFetching}
          names={names}
          lookbackDays={detail.initial_lookback_days}
          filters={filters}
          onFiltersChange={setFilters}
          onAnnounce={setAnnouncement}
        />
      ) : (
        <PreviewSkeleton />
      )}
      <PreviewFooter
        detail={detail}
        names={names}
        run={run}
        busy={preview.isFetching}
        failed={failure !== null}
        onRetry={retry}
        onOpenRule={onOpenRule}
      />
    </div>
  )
}

/** The rule and its accounts, what this page is, what it shares, and what it follows. */
function PreviewHeader({
  heading,
  detail,
  names,
  accounts,
  lead,
  settings,
}: {
  heading: RefObject<HTMLHeadingElement | null>
  detail: RuleDetail
  names: Names
  /** Which accounts and providers the rule connects. */
  accounts: ReactNode
  /** What this page is and when it was made, with a way to make it again. */
  lead: ReactNode
  /** The rule's choices in a few words, with a way to change them. */
  settings: ReactNode
}) {
  const i18n = useI18n()
  const { t } = i18n
  const details = detail.privacy_policy === "copy_details"
  return (
    <header className="rule-preview-header">
      <h1 ref={heading} tabIndex={-1}>
        <span aria-hidden="true">
          {names.source} <ArrowRight className="rule-heading-arrow" />
          {names.destination}
        </span>
        <span className="sr-only">{t("ruleDetails.page.heading", names)}</span>
      </h1>
      {accounts}
      {lead}
      <p className="rule-preview-privacy" data-tone={details ? "attention" : "quiet"}>
        {details ? <Eye aria-hidden="true" /> : <Lock aria-hidden="true" />}
        {details ? t("rulePreview.privacy.details", { destination: names.destination }) : t("rulePreview.privacy.busyOnly")}
      </p>
      {settings}
    </header>
  )
}

function PreviewResults({
  run,
  names,
  lookbackDays,
  busy,
  filters,
  onFiltersChange,
  onAnnounce,
}: {
  run: PreviewRun
  /** Whether a refresh is reading; the results shown are the last ones until it finishes. */
  busy: boolean
  names: Names
  lookbackDays: number
  filters: PreviewFilters
  onFiltersChange: (filters: PreviewFilters) => void
  onAnnounce: (text: string) => void
}) {
  const i18n = useI18n()
  const now = run.completedAt
  // Placing a series at its next date steps through its rule, so it is not redone on every render.
  const placed = useMemo(() => layOut(run.items, now), [run.items, now])
  const layout = useMemo(() => narrowLayout(placed, (item) => matchesFilters(item, filters)), [placed, filters])
  const added = useMemo(() => newSeries(run.items), [run.items])
  const empty = !layout.undated.length && !layout.earlier.length && !layout.upcoming.length
  const zone = useMemo(() => timeZoneName(i18n.formatLocale, now), [i18n.formatLocale, now])
  if (!run.items.length) {
    const from = new Date(now.getFullYear(), now.getMonth(), now.getDate() - lookbackDays)
    return (
      <div className="rule-preview-results" aria-busy={busy} inert={busy}>
        <PreviewEmpty source={names.source} from={from} now={now} />
      </div>
    )
  }
  const written = run.items.some((item) => item.projection)
  const changeFilters = (next: PreviewFilters) => {
    onFiltersChange(next)
    const count = run.items.filter((item) => matchesFilters(item, next)).length
    onAnnounce(i18n.t("rulePreview.filters.showing", { shown: i18n.format.number(count), total: i18n.format.number(run.items.length) }))
  }
  return (
    // Inert while Refresh reads: the dimmed rows are not current, so they are not read or used.
    <div className="rule-preview-results" aria-busy={busy} inert={busy}>
      {!written && (
        <p className="rule-preview-note-line">
          {i18n.t("rulePreview.states.allExcluded", { count: run.items.length, source: names.source })}
        </p>
      )}
      <PreviewFilterBar items={run.items} filters={filters} onChange={changeFilters} />
      {!empty ? (
        <PreviewTable
          layout={layout}
          source={names.source}
          destination={names.destination}
          now={now}
          zone={zone}
          complete={!isFiltered(filters)}
          added={added}
        />
      ) : (
        <p className="rule-preview-no-match">{i18n.t("rulePreview.filters.noMatch")}</p>
      )}
    </div>
  )
}

/** The zone's name without its offset, such as "Spain Time", so it holds across a DST change. */
function timeZoneName(locale: string, at: Date): string {
  const parts = new Intl.DateTimeFormat(locale, { timeZoneName: "shortGeneric" }).formatToParts(at)
  return parts.find((part) => part.type === "timeZoneName")?.value ?? Intl.DateTimeFormat().resolvedOptions().timeZone
}

/** What the preview reads: the source, and the destination too once the rule has written there. */
function readingText(i18n: I18n, detail: RuleDetail, names: Names): string {
  return detail.mapping_count > 0
    ? i18n.t("rulePreview.page.readingBoth", names)
    : i18n.t("rulePreview.page.reading", { source: names.source })
}

/** When the preview was made, with its date once it is not from today, so an old one shows it. */
function leadText(i18n: I18n, run: PreviewRun): string {
  const time = i18n.format.time(run.completedAt)
  if (isToday(run.completedAt, new Date())) return i18n.t("rulePreview.page.leadAt", { time })
  return i18n.t("rulePreview.page.leadOn", { date: i18n.format.date(run.completedAt, { weekday: "short", day: "numeric", month: "short" }), time })
}

/**
 * That nothing is written yet, when the preview was made, and a way to make it again. While it
 * reads, the status above the results says so; Refresh stays put, so focus does not fall back to
 * the page.
 */
function PreviewLead({
  run,
  reading,
  refreshRef,
  onRetry,
}: {
  run: PreviewRun | undefined
  reading: boolean
  refreshRef: RefObject<HTMLButtonElement | null>
  onRetry: () => void
}) {
  const i18n = useI18n()
  return (
    <p className="rule-preview-lead">
      {run ? leadText(i18n, run) : i18n.t("rulePreview.page.lead")}
      <Button
        ref={refreshRef}
        type="button"
        variant="ghost"
        size="sm"
        className="rule-preview-inline-action"
        aria-disabled={reading ? true : undefined}
        onClick={() => !reading && onRetry()}
      >
        {i18n.t("rulePreview.page.previewAgain")}
      </Button>
    </p>
  )
}
