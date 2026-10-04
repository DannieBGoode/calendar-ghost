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
import {
  ApiError,
  api,
  type ConnectedAccount,
  type DiscoveredCalendar,
  type RuleDetail,
} from "@/lib/api"
import { appPathForView, isPlainLeftClick, type OpenRule, type ViewChange } from "@/lib/navigation"
import { plural } from "@/lib/rule-change"
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

  if (rule.isPending || accounts.isPending) return <PageSkeleton label="Loading rule" />
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
      <ArrowLeft aria-hidden="true" /> All rules
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
  const missing = rule.error instanceof ApiError && rule.error.status === 404
  // Stale data still describes the removal this page was showing when the rule disappeared.
  const removed = missing && rule.data?.running?.kind === "removal"
  return (
    <section className="page-section" role="alert">
      <BackToRules onViewChange={onViewChange} />
      <h1>{removed ? "Rule removed" : missing ? "This rule no longer exists" : "Rule details could not load"}</h1>
      <p className="page-intro">
        {removed
          ? "Its removal finished. Activity lists what happened to each of its events."
          : missing
            ? "It may have been removed or replaced. Return to the rules list to continue."
            : "Check that the local service is running, then try again."}
      </p>
      {!missing && (
        <Button variant="outline" onClick={onRetry}>
          <RefreshCw aria-hidden="true" /> Try again
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
  // A failed refresh keeps stale data, which must not keep a finished removal on screen.
  const reported = refreshFailed ? undefined : reportedRemoval(detail.running, detail.mapping_count)
  const removal = reported ?? sessionRemoval
  const accountsById = new Map(accounts.map((account) => [account.id, account]))
  const sourceAccount = accountsById.get(detail.source.connected_account_id)
  const destinationAccount = accountsById.get(detail.destination.connected_account_id)
  const destinationConnected = destinationAccount?.state === "connected"
  const disconnected = [sourceAccount, destinationAccount].some(
    (account) => account?.state === "disconnected",
  )
  const sourceName = ruleEndpointLabel(
    detail.source,
    sourceAccount,
    calendarsByAccount.get(detail.source.connected_account_id),
  ).calendar
  const destinationName = ruleEndpointLabel(
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
            stopped={detail.state === "degraded" || disconnected}
            working={work?.kind}
          />
          <RuleNextAction
            state={displayState}
            disconnected={disconnected}
            pending={pending}
            describedBy={displayState === "dry_run_validated" ? "rule-preview-ready" : undefined}
            onRun={run}
            onViewChange={onViewChange}
          />
          <RuleCommandMenu
            state={displayState}
            disconnected={disconnected}
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
        disconnected={disconnected}
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
  return (
    <div className="rule-heading">
      <h1 ref={ref} tabIndex={-1}>
        {sourceName} <ArrowRight aria-hidden="true" className="rule-heading-arrow" />
        <span className="sr-only"> to </span>
        {destinationName}
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
  disconnected,
  work,
  feedback,
  sourceName,
  destinationName,
  now,
}: {
  detail: RuleDetail
  displayState: string
  disconnected: boolean
  work: RuleWork | null
  feedback: RuleFeedback | undefined
  sourceName: string
  destinationName: string
  now: number
}) {
  const stopped = displayState === "degraded" && !disconnected
  return (
    <>
      {stopped && (
        <div className="rule-recovery-note">
          <ShieldAlert aria-hidden="true" />
          <p>{recoveryExplanation(detail.last_sync, now)}</p>
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
            <strong>Preview required.</strong> The policy changed. Preview this rule, then start syncing;{" "}
            {plural(detail.mapping_count, "existing projection")} will be rewritten on the next run.
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
