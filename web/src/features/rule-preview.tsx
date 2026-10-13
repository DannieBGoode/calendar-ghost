import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, ArrowRight, Eye, LoaderCircle, Lock } from "lucide-react"
import { useEffect, useRef, useState, type RefObject } from "react"

import { GhostMark } from "@/components/ghost-mark"
import { PageSkeleton } from "@/components/page-skeleton"
import { LiveAnnouncement } from "@/components/rule-commands"
import { Button } from "@/components/ui/button"
import { PreviewFilterBar } from "@/features/rule-preview-filters"
import { PreviewEmpty, PreviewFailurePanel, PreviewSkeleton } from "@/features/rule-preview-states"
import { OutcomeSigns, PreviewTable } from "@/features/rule-preview-table"
import { useI18n } from "@/i18n/provider"
import { ApiError, api, type ConnectedAccount, type RuleDetail } from "@/lib/api"
import { appPathForRule, isPlainLeftClick, type OpenRule, type ViewChange } from "@/lib/navigation"
import { ruleEndpointLabel } from "@/lib/rule-endpoint"
import { NO_FILTERS, layOut, matchesFilters, outcomeCounts, type PreviewFilters, type PreviewItem } from "@/lib/rule-preview"
import { previewFailure } from "@/lib/rule-preview-failure"
import { outcomeParts } from "@/lib/rule-preview-text"
import { enabledMessage } from "@/lib/rule-run"
import { RULE_CHANGE_QUERIES, rulePreviewKey } from "@/lib/use-rule-commands"
import { useRuleCalendars, type CalendarsByAccount } from "@/lib/use-rule-calendars"

type Names = { source: string; destination: string }
/** What enabling answers when the rule is no longer the one previewed. */
const CHANGED_CODES = ["rule_not_executable", "invalid_state_transition"]
type PreviewRun = { items: PreviewItem[]; completedAt: Date }
/** Why starting the rule did not work: it changed since the preview, or something else. */
type StartFailure = "changed" | "failed"

/** The preview runs once per visit and is kept for the session; "Preview again" runs it anew. */
function useRulePreview(ruleId: string) {
  const queryClient = useQueryClient()
  return useQuery({
    queryKey: rulePreviewKey(ruleId),
    queryFn: async (): Promise<PreviewRun> => {
      try {
        const result = await api.previewRule(ruleId)
        return { items: result.items, completedAt: new Date() }
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
  const preview = useRulePreview(ruleId)
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
  const run = preview.isFetching ? undefined : preview.data
  const failure = !preview.isFetching && preview.error
    ? previewFailure(i18n, preview.error, {
        ruleState: detail.state,
        ruleAccounts: [detail.source.connected_account_id, detail.destination.connected_account_id],
        accounts,
      })
    : null
  const retry = () => void preview.refetch()
  const openRule = () => onOpenRule(detail.id)
  return (
    <div className="page-section rule-preview-page">
      <LiveAnnouncement text={announcement} />
      <PreviewHeader heading={heading} detail={detail} names={names} items={run?.items} />
      {failure ? (
        <PreviewFailurePanel failure={failure} ruleId={detail.id} onRetry={retry} onOpenRule={openRule} onViewChange={onViewChange} />
      ) : run ? (
        <PreviewResults
          run={run}
          names={names}
          lookbackDays={detail.initial_lookback_days}
          onAnnounce={setAnnouncement}
          onChangeRule={openRule}
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

/** The rule, what this page is, what starting it does, and what it shares. */
function PreviewHeader({
  heading,
  detail,
  names,
  items,
}: {
  heading: RefObject<HTMLHeadingElement | null>
  detail: RuleDetail
  names: Names
  items: PreviewItem[] | undefined
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
      <p className="rule-preview-lead">{t("rulePreview.page.lead")}</p>
      {items ? (
        <p className="rule-preview-counts" aria-label={t("rulePreview.counts.label")}>
          <OutcomeSigns parts={outcomeParts(i18n, outcomeCounts(items))} />
        </p>
      ) : (
        <p className="rule-preview-reading">
          <span className="rule-preview-reading-ghost"><GhostMark /></span>
          {detail.mapping_count > 0
            ? t("rulePreview.page.readingBoth", names)
            : t("rulePreview.page.reading", { source: names.source })}
        </p>
      )}
      <p className="rule-preview-privacy" data-tone={details ? "attention" : "quiet"}>
        {details ? <Eye aria-hidden="true" /> : <Lock aria-hidden="true" />}
        {details ? t("rulePreview.privacy.details", { destination: names.destination }) : t("rulePreview.privacy.busyOnly")}
      </p>
    </header>
  )
}

function PreviewResults({
  run,
  names,
  lookbackDays,
  onAnnounce,
  onChangeRule,
}: {
  run: PreviewRun
  names: Names
  lookbackDays: number
  onAnnounce: (text: string) => void
  /** Opens the rule, where its policy says what syncs. */
  onChangeRule: () => void
}) {
  const i18n = useI18n()
  const [filters, setFilters] = useState<PreviewFilters>(NO_FILTERS)
  const now = run.completedAt
  const shown = run.items.filter((item) => matchesFilters(item, filters))
  if (!run.items.length) {
    const from = new Date(now.getFullYear(), now.getMonth(), now.getDate() - lookbackDays)
    return <PreviewEmpty source={names.source} from={from} />
  }
  const written = run.items.some((item) => item.projection)
  const changeFilters = (next: PreviewFilters) => {
    setFilters(next)
    const count = run.items.filter((item) => matchesFilters(item, next)).length
    onAnnounce(i18n.t("rulePreview.filters.showing", { shown: i18n.format.number(count), total: i18n.format.number(run.items.length) }))
  }
  return (
    <>
      {!written && (
        <p className="rule-preview-note-line">
          {i18n.t("rulePreview.states.allExcluded", { count: run.items.length, source: names.source })}{" "}
          <Button type="button" variant="ghost" size="sm" onClick={onChangeRule}>
            {i18n.t("rulePreview.states.changeWhatSyncs")}
          </Button>
        </p>
      )}
      <PreviewFilterBar items={run.items} filters={filters} shown={shown.length} onChange={changeFilters} />
      <p className="rule-preview-zone">{i18n.t("rulePreview.filters.timeZone", { zone: timeZoneName(i18n.formatLocale, now) })}</p>
      {shown.length ? (
        <PreviewTable layout={layOut(shown, now)} source={names.source} destination={names.destination} now={now} />
      ) : (
        <p className="rule-preview-no-match">{i18n.t("rulePreview.filters.noMatch")}</p>
      )}
    </>
  )
}

function timeZoneName(locale: string, at: Date): string {
  const parts = new Intl.DateTimeFormat(locale, { timeZoneName: "short" }).formatToParts(at)
  return parts.find((part) => part.type === "timeZoneName")?.value ?? Intl.DateTimeFormat().resolvedOptions().timeZone
}

/** Back to the rule, when the preview was made, and the page's one primary action. */
function PreviewFooter({
  detail,
  names,
  run,
  busy,
  failed,
  onRetry,
  onOpenRule,
}: {
  detail: RuleDetail
  names: Names
  run: PreviewRun | undefined
  busy: boolean
  failed: boolean
  onRetry: () => void
  onOpenRule: OpenRule
}) {
  const i18n = useI18n()
  const queryClient = useQueryClient()
  const enable = useMutation({
    mutationFn: () => api.enableRule(detail.id),
    onError: () => void queryClient.invalidateQueries({ queryKey: ["rule", detail.id] }),
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: rulePreviewKey(detail.id) })
      await Promise.all(
        [...RULE_CHANGE_QUERIES, ["rule", detail.id]].map((queryKey) => queryClient.invalidateQueries({ queryKey })),
      )
      onOpenRule(detail.id, { notice: enabledMessage(i18n, names.destination) })
    },
  })
  // Another tab or a scheduled run moved the rule on; its details are refetched below.
  const changed = enable.error instanceof ApiError && CHANGED_CODES.includes(enable.error.code ?? "")
  const canStart = run !== undefined && !failed && !changed && detail.state === "dry_run_validated"
  const startFailure: StartFailure | null = enable.error ? (changed ? "changed" : "failed") : null
  return (
    <footer className="rule-preview-footer">
      <div className="rule-preview-footer-inner">
        <a
          className="back-link"
          href={appPathForRule(detail.id)}
          onClick={(event) => {
            if (!isPlainLeftClick(event)) return
            event.preventDefault()
            onOpenRule(detail.id)
          }}
        >
          <ArrowLeft aria-hidden="true" /> {i18n.t("rulePreview.page.back")}
        </a>
        <PreviewStamp
          run={run}
          busy={busy}
          outcome={startFailure}
          onRetry={() => {
            enable.reset()
            onRetry()
          }}
        />
        {detail.state !== "enabled" && (
          <StartButton
            destination={names.destination}
            ready={canStart}
            starting={enable.isPending}
            busy={busy}
            onStart={() => enable.mutate()}
          />
        )}
      </div>
    </footer>
  )
}

/** When the preview was made and a way to make it again, or why starting did not work. */
function PreviewStamp({
  run,
  busy,
  outcome,
  onRetry,
}: {
  run: PreviewRun | undefined
  busy: boolean
  outcome: StartFailure | null
  onRetry: () => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  let text: string | null = null
  if (outcome === "changed") text = t("rulePreview.page.changedSincePreview")
  else if (outcome === "failed") text = t("rulePreview.page.enableFailed")
  else if (run) text = t("rulePreview.page.previewedAt", { time: i18n.format.time(run.completedAt) })
  else if (busy) text = t("rulePreview.page.previewing")
  return (
    <p className="rule-preview-stamp" role={outcome ? "alert" : undefined}>
      {text}
      {(run !== undefined || outcome === "changed") && (
        <Button type="button" variant="ghost" size="sm" onClick={onRetry}>
          {t("rulePreview.page.previewAgain")}
        </Button>
      )}
    </p>
  )
}

function StartButton({
  destination,
  ready,
  starting,
  busy,
  onStart,
}: {
  destination: string
  ready: boolean
  starting: boolean
  busy: boolean
  onStart: () => void
}) {
  const { t } = useI18n()
  const blocked = !ready || starting
  return (
    <div className="rule-preview-start">
      <Button
        className="rule-preview-start-button"
        aria-disabled={blocked ? true : undefined}
        aria-describedby={busy ? "rule-preview-start-note" : undefined}
        onClick={() => !blocked && onStart()}
      >
        {starting ? (
          <>
            <LoaderCircle aria-hidden="true" className="work-spinner" /> {t("rulePreview.page.starting")}
          </>
        ) : (
          t("rulePreview.page.startSyncing", { destination })
        )}
      </Button>
      {busy && (
        <span id="rule-preview-start-note" className="rule-preview-start-note">
          {t("rulePreview.page.availableWhenDone")}
        </span>
      )}
    </div>
  )
}
