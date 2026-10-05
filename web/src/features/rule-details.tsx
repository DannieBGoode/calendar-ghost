import { useQueries, useQuery } from "@tanstack/react-query"
import { ArrowLeft, ArrowRight, RefreshCw, ShieldAlert } from "lucide-react"
import { useEffect, useRef, type RefObject } from "react"

import { PageSkeleton } from "@/components/page-skeleton"
import {
  LiveAnnouncement,
  PreviewReadyNote,
  RuleCommandMenu,
  RuleFeedbackNote,
  RuleNextAction,
  RuleStatusBadge,
  RuleWorkNote,
} from "@/components/rule-commands"
import { RuleEndpoint } from "@/components/rule-endpoint"
import { Button } from "@/components/ui/button"
import { CalendarReplacement } from "@/features/calendar-replacement"
import { RuleFacts, RuleRuns } from "@/features/rule-details-facts"
import { PolicyEditor } from "@/features/rule-policy-editor"
import { RuleRemoval } from "@/features/rule-removal"
import { useI18n } from "@/i18n/provider"
import { rich } from "@/i18n/rich"
import {
  ApiError,
  api,
  type ConnectedAccount,
  type DiscoveredCalendar,
  type RuleDetail,
} from "@/lib/api"
import { appPathForView, isPlainLeftClick, type OpenRule, type ViewChange } from "@/lib/navigation"
import { needsReauthorization } from "@/lib/account-summary"
import { ruleEndpointLabel } from "@/lib/rule-endpoint"
import { REMOVAL_REFRESH_MS, reportedRemoval, useActiveRemoval, type ActiveRemoval } from "@/lib/rule-removal"
import { recoveryExplanation } from "@/lib/rule-run"
import { busyCommand, ruleWork, workRefreshInterval, type RuleWork } from "@/lib/rule-work"
import { useNow } from "@/lib/use-now"
import { useRuleCommands, type RuleFeedback } from "@/lib/use-rule-commands"

const PREVIEWABLE_STATES = ["draft", "paused", "degraded"]

type RuleCommands = ReturnType<typeof useRuleCommands>
type CalendarsByAccount = Map<string, DiscoveredCalendar[] | undefined>

export function RuleDetailsView({
  ruleId,
  notice,
  onViewChange,
  onOpenRule,
}: {
  ruleId: string
  notice: string | null
  onViewChange: ViewChange
  onOpenRule: OpenRule
}) {
  const { t } = useI18n()
  const now = useNow()
  const commands = useRuleCommands()
  const sessionRemoval = useActiveRemoval(ruleId)
  const rule = useQuery({
    queryKey: ["rule", ruleId],
    queryFn: () => api.rule(ruleId),
    retry: false,
    // A removal commits each projection it deletes, so refresh quickly to show its progress.
    refetchInterval: (query) =>
      sessionRemoval ? REMOVAL_REFRESH_MS : workRefreshInterval(query.state.data && [query.state.data], 60_000, commands.pending),
  })
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: api.accounts })
  const heading = useRef<HTMLHeadingElement>(null)
  const loadedRuleId = rule.data?.id
  const { calendarsByAccount, namesReady } = useRuleCalendars(rule.data, accounts.data)
  useEffect(() => {
    if (loadedRuleId && namesReady) heading.current?.focus()
  }, [loadedRuleId, namesReady])

  if (rule.isPending || accounts.isPending) return <PageSkeleton label={t("ruleDetails.page.loading")} />
  // The last refresh of a finishing removal can find the rule gone before the removal returns.
  if (!rule.data || (rule.error && !sessionRemoval) || accounts.error) {
    return (
      <RuleLoadFailure
        rule={rule}
        onRetry={() => {
          void rule.refetch()
          void accounts.refetch()
        }}
        onViewChange={onViewChange}
      />
    )
  }

  return (
    <RuleDetailsPage
      detail={rule.data}
      refreshFailed={rule.error !== null}
      sessionRemoval={sessionRemoval}
      accounts={accounts.data}
      calendarsByAccount={calendarsByAccount}
      heading={heading}
      commands={commands}
      now={now}
      notice={notice}
      onViewChange={onViewChange}
      onOpenRule={onOpenRule}
    />
  )
}

/** Calendar names for the rule's connected accounts, and whether the heading can name both yet. */
function useRuleCalendars(detail: RuleDetail | undefined, accounts: ConnectedAccount[] | undefined) {
  const accountIds = detail
    ? [...new Set([detail.source.connected_account_id, detail.destination.connected_account_id])]
    : []
  const connectedIds = accountIds.filter(
    (id) => accounts?.find((account) => account.id === id)?.state === "connected",
  )
  const calendarQueries = useQueries({
    queries: connectedIds.map((accountId) => ({
      queryKey: ["calendars", accountId],
      queryFn: () => api.calendars(accountId),
      staleTime: 5 * 60 * 1000,
    })),
  })
  const calendarsByAccount: CalendarsByAccount = new Map(
    connectedIds.map((accountId, index) => [accountId, calendarQueries[index]?.data]),
  )

  // Wait for calendar names so the focused heading never announces placeholder names; names
  // recorded when Google last listed the calendars serve until it answers again.
  const namesRecorded = Boolean(detail?.source.calendar_name && detail.destination.calendar_name)
  const namesReady = namesRecorded || calendarQueries.every((query) => !query.isPending)
  return { calendarsByAccount, namesReady }
}

function BackToRules({ onViewChange }: { onViewChange: ViewChange }) {
  const { t } = useI18n()
  return (
    <a
      className="back-link"
      href={appPathForView("rules")}
      onClick={(event) => {
        if (!isPlainLeftClick(event)) return
        event.preventDefault()
        onViewChange("rules")
      }}
    >
      <ArrowLeft aria-hidden="true" /> {t("ruleDetails.page.back")}
    </a>
  )
}

function RuleLoadFailure({
  rule,
  onRetry,
  onViewChange,
}: {
  rule: { data: RuleDetail | undefined; error: Error | null }
  onRetry: () => void
  onViewChange: ViewChange
}) {
  const { t } = useI18n()
  const missing = rule.error instanceof ApiError && rule.error.status === 404
  // Stale data still describes the removal this page was showing when the rule disappeared.
  const removed = missing && rule.data?.running?.kind === "removal"
  return (
    <section className="page-section" role="alert">
      <BackToRules onViewChange={onViewChange} />
      <h1>
        {removed
          ? t("ruleDetails.page.removedTitle")
          : missing
            ? t("ruleDetails.page.missingTitle")
            : t("ruleDetails.page.loadFailedTitle")}
      </h1>
      <p className="page-intro">
        {removed
          ? t("ruleDetails.page.removedBody")
          : missing
            ? t("ruleDetails.page.missingBody")
            : t("ruleDetails.page.loadFailedBody")}
      </p>
      {!missing && (
        <Button variant="outline" onClick={onRetry}>
          <RefreshCw aria-hidden="true" /> {t("ruleDetails.page.tryAgain")}
        </Button>
      )}
    </section>
  )
}

function RuleDetailsPage({
  detail,
  refreshFailed,
  sessionRemoval,
  accounts,
  calendarsByAccount,
  heading,
  commands,
  now,
  notice,
  onViewChange,
  onOpenRule,
}: {
  detail: RuleDetail
  refreshFailed: boolean
  sessionRemoval: ActiveRemoval | undefined
  accounts: ConnectedAccount[]
  calendarsByAccount: CalendarsByAccount
  heading: RefObject<HTMLHeadingElement | null>
  commands: RuleCommands
  now: number
  notice: string | null
  onViewChange: ViewChange
  onOpenRule: OpenRule
}) {
  const i18n = useI18n()
  // A failed refresh keeps stale data, which must not keep a finished removal on screen.
  const reported = refreshFailed ? undefined : reportedRemoval(detail.running, detail.mapping_count)
  const removal = reported ?? sessionRemoval
  const accountsById = new Map(accounts.map((account) => [account.id, account]))
  const sourceAccount = accountsById.get(detail.source.connected_account_id)
  const destinationAccount = accountsById.get(detail.destination.connected_account_id)
  const destinationConnected = destinationAccount?.state === "connected"
  // The account to reauthorize first: disconnected, or no longer accepted by Google.
  const unauthorized = [sourceAccount, destinationAccount].find(
    (account): account is ConnectedAccount => account !== undefined && needsReauthorization(account),
  )
  const sourceName = ruleEndpointLabel(
    i18n,
    detail.source,
    sourceAccount,
    calendarsByAccount.get(detail.source.connected_account_id),
  ).calendar
  const destinationName = ruleEndpointLabel(
    i18n,
    detail.destination,
    destinationAccount,
    calendarsByAccount.get(detail.destination.connected_account_id),
  ).calendar
  const displayState = removal ? "removing" : detail.state
  const work = ruleWork({
    pending: commands.pending[detail.id],
    pendingSince: commands.pendingSince[detail.id],
    running: detail.running,
    removing: removal !== undefined,
  })
  const pending = busyCommand(commands.pending[detail.id], work)
  const run = (command: Parameters<typeof commands.run>[1]) =>
    void commands.run(detail.id, command, destinationName, () => heading.current)

  return (
    <div className="page-section rule-details-page">
      <LiveAnnouncement text={commands.announcement} />
      <BackToRules onViewChange={onViewChange} />
      {notice && <p className="page-notice">{notice}</p>}
      <div className="page-heading-row">
        <RuleHeading
          ref={heading}
          detail={detail}
          sourceAccount={sourceAccount}
          destinationAccount={destinationAccount}
          calendarsByAccount={calendarsByAccount}
          sourceName={sourceName}
          destinationName={destinationName}
        />
        <div className="rule-actions">
          <RuleStatusBadge
            state={displayState}
            stopped={detail.state === "degraded" || unauthorized !== undefined}
            working={work?.kind}
          />
          <RuleNextAction
            state={displayState}
            reauthorize={unauthorized}
            pending={pending}
            describedBy={displayState === "dry_run_validated" ? "rule-preview-ready" : undefined}
            onRun={run}
            onViewChange={onViewChange}
          />
          <RuleCommandMenu
            state={displayState}
            unauthorized={unauthorized !== undefined}
            pending={pending}
            source={sourceName}
            destination={destinationName}
            onRun={run}
          />
        </div>
      </div>

      <RuleNotes
        detail={detail}
        displayState={displayState}
        unauthorized={unauthorized}
        work={work}
        feedback={commands.feedback[detail.id]}
        sourceName={sourceName}
        destinationName={destinationName}
        now={now}
      />
      <RuleFacts detail={detail} destinationName={destinationName} />
      <RuleRuns
        detail={detail}
        sourceName={sourceName}
        destinationName={destinationName}
        now={now}
        onViewChange={onViewChange}
      />
      <RuleChanges
        detail={detail}
        accounts={accounts}
        removing={removal !== undefined || detail.state === "disabled"}
        destinationName={destinationName}
        destinationConnected={destinationConnected}
        onSaved={(feedback) => commands.notify(detail.id, feedback)}
        onViewChange={onViewChange}
        onOpenRule={onOpenRule}
      />
    </div>
  )
}

function RuleHeading({
  ref,
  detail,
  sourceAccount,
  destinationAccount,
  calendarsByAccount,
  sourceName,
  destinationName,
}: {
  ref: RefObject<HTMLHeadingElement | null>
  detail: RuleDetail
  sourceAccount: ConnectedAccount | undefined
  destinationAccount: ConnectedAccount | undefined
  calendarsByAccount: CalendarsByAccount
  sourceName: string
  destinationName: string
}) {
  const { t } = useI18n()
  return (
    <div className="rule-heading">
      <h1 ref={ref} tabIndex={-1}>
        {/* The arrow reads as one sentence to assistive technology, not as glued fragments. */}
        <span aria-hidden="true">
          {sourceName} <ArrowRight className="rule-heading-arrow" />
          {destinationName}
        </span>
        <span className="sr-only">
          {t("ruleDetails.page.heading", { source: sourceName, destination: destinationName })}
        </span>
      </h1>
      <div className="rule-direction rule-details-direction">
        <RuleEndpoint
          account={sourceAccount}
          endpoint={detail.source}
          calendars={calendarsByAccount.get(detail.source.connected_account_id)}
          role="Source"
        />
        <ArrowRight aria-hidden="true" />
        <RuleEndpoint
          account={destinationAccount}
          endpoint={detail.destination}
          calendars={calendarsByAccount.get(detail.destination.connected_account_id)}
          role="Destination"
        />
      </div>
    </div>
  )
}

function RuleNotes({
  detail,
  displayState,
  unauthorized,
  work,
  feedback,
  sourceName,
  destinationName,
  now,
}: {
  detail: RuleDetail
  displayState: string
  unauthorized: ConnectedAccount | undefined
  work: RuleWork | null
  feedback: RuleFeedback | undefined
  sourceName: string
  destinationName: string
  now: number
}) {
  const i18n = useI18n()
  const stopped = displayState === "degraded" && !unauthorized
  return (
    <>
      {unauthorized && displayState !== "removing" && (
        <div className="rule-recovery-note">
          <ShieldAlert aria-hidden="true" />
          <p>{i18n.t("rules.list.stoppedDisconnected", { accounts: unauthorized.email })}</p>
        </div>
      )}
      {stopped && (
        <div className="rule-recovery-note">
          <ShieldAlert aria-hidden="true" />
          <p>{recoveryExplanation(i18n, detail.last_sync, now)}</p>
        </div>
      )}
      {displayState === "dry_run_validated" && (
        <PreviewReadyNote id="rule-preview-ready" preview={detail.latest_preview} destination={destinationName} />
      )}
      {/* Removal shows its own progress in the removal section. */}
      {work && work.kind !== "removal" ? (
        <RuleWorkNote work={work} source={sourceName} destination={destinationName} />
      ) : (
        <RuleFeedbackNote feedback={feedback} />
      )}

      {detail.reprojection_required && PREVIEWABLE_STATES.includes(displayState) && (
        <div className="rule-recovery-note">
          <ShieldAlert aria-hidden="true" />
          <p>
            {rich(i18n.t("ruleDetails.page.reprojectionRequired", { count: detail.mapping_count }), {
              strong: (text) => <strong>{text}</strong>,
            })}
          </p>
        </div>
      )}
    </>
  )
}

/** The policy, calendar, and removal sections; a rule being removed can only finish its removal. */
function RuleChanges({
  detail,
  accounts,
  removing,
  destinationName,
  destinationConnected,
  onSaved,
  onViewChange,
  onOpenRule,
}: {
  detail: RuleDetail
  accounts: ConnectedAccount[]
  removing: boolean
  destinationName: string
  destinationConnected: boolean
  onSaved: (feedback: RuleFeedback) => void
  onViewChange: ViewChange
  onOpenRule: OpenRule
}) {
  return (
    <>
      {!removing && <PolicyEditor detail={detail} destinationName={destinationName} onSaved={onSaved} />}
      {!removing && (
        <CalendarReplacement
          detail={detail}
          accounts={accounts}
          destinationName={destinationName}
          destinationConnected={destinationConnected}
          onReplaced={(nextRuleId, message) => onOpenRule(nextRuleId, { notice: message })}
        />
      )}
      <RuleRemoval
        detail={detail}
        destinationName={destinationName}
        destinationConnected={destinationConnected}
        onRemoved={(outcome) => {
          onViewChange("rules", { notice: outcome.message, noticeTone: outcome.attention ? "attention" : undefined })
        }}
      />
    </>
  )
}
