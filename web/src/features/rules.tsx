import { useQuery } from "@tanstack/react-query"
import { ArrowRight, CheckCircle2, Plus, ShieldAlert } from "lucide-react"
import { useRef, useState, type RefObject } from "react"

import { GhostMark } from "@/components/ghost-mark"
import { LoadFailure } from "@/components/load-failure"
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
import { RuleBuilder } from "@/features/rule-builder"
import { useI18n } from "@/i18n/provider"
import { rich } from "@/i18n/rich"
import type { MessageKey } from "@/i18n/types"
import { api, type ConnectedAccount, type RulePolicyPayload, type RuleSummary } from "@/lib/api"
import { appPathForRule, appPathForView, isPlainLeftClick, type OpenRule, type ViewChange } from "@/lib/navigation"
import { useRemovingRuleIds } from "@/lib/rule-removal"
import { lastRunLabel } from "@/lib/rule-run"
import { busyCommand, ruleWork, workRefreshInterval, type RuleWork } from "@/lib/rule-work"
import { useNow } from "@/lib/use-now"
import { useRuleCommands, type RuleFeedback } from "@/lib/use-rule-commands"
import { useRuleEndpoints, type RuleEndpoints } from "@/lib/use-rule-endpoints"

export { RuleBuilder }

const POLICY_SUMMARY_KEYS: Record<RulePolicyPayload["privacy_policy"], Record<"allDay" | "timedOnly", MessageKey>> = {
  busy_only: {
    allDay: "rules.list.policySummary.busyOnlyAllDay",
    timedOnly: "rules.list.policySummary.busyOnlyTimedOnly",
  },
  copy_details: {
    allDay: "rules.list.policySummary.copyDetailsAllDay",
    timedOnly: "rules.list.policySummary.copyDetailsTimedOnly",
  },
}

type RulesNoticeText = { text: string; attention: boolean }

type RulesViewProps = {
  notice: RulesNoticeText | null
  createRule: boolean
  onViewChange: ViewChange
  onOpenRule: OpenRule
}

export function RulesView({
  notice,
  createRule,
  onViewChange,
  onOpenRule,
}: RulesViewProps) {
  const { t } = useI18n()
  const now = useNow()
  const commands = useRuleCommands()
  const rules = useQuery({
    queryKey: ["rules"],
    queryFn: api.rules,
    refetchInterval: (query) => workRefreshInterval(query.state.data, 60_000, commands.pending),
  })
  const { accounts, endpoints } = useRuleEndpoints(rules.data ?? [])
  const removingIds = useRemovingRuleIds(rules.data)
  const [builderChoice, setBuilderChoice] = useState<boolean | null>(null)
  const [noticeDismissed, setNoticeDismissed] = useState(false)
  const createButton = useRef<HTMLButtonElement>(null)
  const rows = useRef(new Map<string, HTMLLIElement>())

  if (rules.isPending || accounts.isPending) return <PageSkeleton label={t("rules.list.loading")} />
  if (rules.error || accounts.error) {
    return (
      <LoadFailure
        title={t("rules.list.loadFailure")}
        onRetry={() => {
          void rules.refetch()
          void accounts.refetch()
        }}
      />
    )
  }

  const connected = accounts.data.filter((account) => account.state === "connected")
  // Arriving from "Create a rule" opens the builder directly; nothing else opens it unasked.
  const showBuilder = builderChoice ?? (createRule && connected.length > 0)

  return (
    <div className="page-section">
      <LiveAnnouncement text={commands.announcement} />
      <RulesHeading
        createButton={createButton}
        showBuilder={showBuilder}
        noAccounts={connected.length === 0}
        onToggleBuilder={() => setBuilderChoice(!showBuilder)}
        onViewChange={onViewChange}
      />
      <RulesNotice
        notice={notice}
        dismissed={noticeDismissed}
        onDismiss={() => setNoticeDismissed(true)}
        onViewChange={onViewChange}
      />
      {showBuilder && (
        <RuleBuilder
          accounts={connected}
          onCreated={(rule) => {
            setBuilderChoice(false)
            commands.notify(rule.id, {
              tone: "success",
              text: t("rules.list.draftSavedNotice"),
            })
            createButton.current?.focus()
          }}
        />
      )}
      {rules.data.length === 0 ? (
        <NoRulesNote builderOpen={showBuilder} connected={connected} />
      ) : (
        <ul className="rule-list page-card" aria-label={t("rules.list.ariaLabel")}>
          {rules.data.map((rule) => (
            <RuleRow
              key={rule.id}
              rule={rule}
              endpoints={endpoints(rule)}
              removing={removingIds.has(rule.id)}
              commands={commands}
              rows={rows}
              now={now}
              onViewChange={onViewChange}
              onOpenRule={onOpenRule}
            />
          ))}
        </ul>
      )}
    </div>
  )
}

function RulesHeading({
  createButton,
  showBuilder,
  noAccounts,
  onToggleBuilder,
  onViewChange,
}: {
  createButton: RefObject<HTMLButtonElement | null>
  showBuilder: boolean
  noAccounts: boolean
  onToggleBuilder: () => void
  onViewChange: ViewChange
}) {
  const { t } = useI18n()
  return (
    <div className="page-heading-row">
      <div>
        <h1>{t("rules.list.heading")}</h1>
        <p className="page-intro">{t("rules.list.intro")}</p>
      </div>
      <div className="heading-action">
        <Button
          ref={createButton}
          variant={showBuilder ? "outline" : "default"}
          disabled={noAccounts}
          onClick={onToggleBuilder}
          aria-expanded={showBuilder}
          aria-controls="rule-builder"
          aria-describedby={noAccounts ? "create-rule-hint" : undefined}
        >
          {showBuilder ? t("rules.list.closeBuilder") : <><Plus aria-hidden="true" /> {t("rules.list.createButton")}</>}
        </Button>
        {noAccounts && (
          <p id="create-rule-hint" className="action-hint">
            {rich(t("rules.list.connectAccountHint"), {
              link: (text) => (
                <a
                  href={appPathForView("settings")}
                  onClick={(event) => {
                    if (!isPlainLeftClick(event)) return
                    event.preventDefault()
                    onViewChange("settings")
                  }}
                >
                  {text}
                </a>
              ),
            })}
          </p>
        )}
      </div>
    </div>
  )
}

function RulesNotice({
  notice,
  dismissed,
  onDismiss,
  onViewChange,
}: {
  notice: RulesNoticeText | null
  dismissed: boolean
  onDismiss: () => void
  onViewChange: ViewChange
}) {
  const { t } = useI18n()
  if (!notice || dismissed) return null
  return (
    <div className="page-notice" data-tone={notice.attention ? "attention" : undefined}>
      {notice.attention ? <ShieldAlert aria-hidden="true" /> : <CheckCircle2 aria-hidden="true" />}
      <p>{notice.text}</p>
      <div className="page-notice-actions">
        {notice.attention && (
          <Button variant="outline" asChild>
            <a
              href={appPathForView("activity")}
              onClick={(event) => {
                if (!isPlainLeftClick(event)) return
                event.preventDefault()
                onViewChange("activity")
              }}
            >
              {t("rules.list.reviewInActivity")}
            </a>
          </Button>
        )}
        <Button variant="ghost" onClick={onDismiss}>{t("rules.list.dismiss")}</Button>
      </div>
    </div>
  )
}

/** Hidden while the builder is open, which already shows the way forward. */
function NoRulesNote({ builderOpen, connected }: { builderOpen: boolean; connected: ConnectedAccount[] }) {
  const { t } = useI18n()
  if (builderOpen) return null
  return (
    <section className="empty-note" aria-labelledby="no-rules-title">
      <GhostMark className="empty-ghost" />
      <div>
        <h2 id="no-rules-title">{t("rules.list.empty.title")}</h2>
        <p>{connected.length === 0 ? t("rules.list.empty.connectFirst") : t("rules.list.empty.createFirst")}</p>
      </div>
    </section>
  )
}

type RuleRowProps = {
  rule: RuleSummary
  endpoints: RuleEndpoints
  removing: boolean
  commands: ReturnType<typeof useRuleCommands>
  rows: RefObject<Map<string, HTMLLIElement>>
  now: number
  onViewChange: ViewChange
  onOpenRule: OpenRule
}

function RuleRow({ rule, endpoints, removing, commands, rows, now, onViewChange, onOpenRule }: RuleRowProps) {
  const { t } = useI18n()
  const { source, destination, disconnected } = endpoints
  const stopped = rule.state === "degraded" || disconnected.length > 0
  const work = ruleWork({
    pending: commands.pending[rule.id],
    pendingSince: commands.pendingSince[rule.id],
    running: rule.running,
    removing,
  })
  const pending = busyCommand(commands.pending[rule.id], work)
  const state = removing ? "removing" : rule.state
  const headingId = `rule-${rule.id}-name`
  const previewId = `rule-${rule.id}-preview`
  const run = (command: Parameters<typeof commands.run>[1]) =>
    void commands.run(rule.id, command, destination.name, () => rows.current.get(rule.id) ?? null)
  return (
    <li
      className="rule-row"
      tabIndex={-1}
      aria-labelledby={headingId}
      aria-busy={work ? true : undefined}
      ref={(element) => {
        if (element) rows.current.set(rule.id, element)
        else rows.current.delete(rule.id)
      }}
    >
      <div className="rule-main">
        <RuleSummaryLine rule={rule} endpoints={endpoints} headingId={headingId} now={now} />
        <div className="rule-actions">
          <RuleStatusBadge state={state} stopped={stopped} working={work?.kind} />
          <RuleNextAction
            state={state}
            disconnected={disconnected.length > 0}
            pending={pending}
            describedBy={state === "dry_run_validated" ? `${headingId} ${previewId}` : headingId}
            onRun={run}
            onViewChange={onViewChange}
          />
          <Button variant="ghost" asChild>
            <a
              href={appPathForRule(rule.id)}
              onClick={(event) => {
                if (!isPlainLeftClick(event)) return
                event.preventDefault()
                onOpenRule(rule.id)
              }}
              aria-label={t("rules.list.detailsLabel", { source: source.name, destination: destination.name })}
            >
              {t("rules.list.detailsLink")} <ArrowRight aria-hidden="true" />
            </a>
          </Button>
          <RuleCommandMenu
            state={state}
            disconnected={disconnected.length > 0}
            pending={pending}
            source={source.name}
            destination={destination.name}
            reserveSpace
            onRun={run}
          />
        </div>
      </div>
      <RuleNotes
        rule={rule}
        endpoints={endpoints}
        state={state}
        stopped={stopped}
        work={work}
        feedback={commands.feedback[rule.id]}
        previewId={previewId}
      />
    </li>
  )
}

function RuleSummaryLine({
  rule,
  endpoints,
  headingId,
  now,
}: {
  rule: RuleSummary
  endpoints: RuleEndpoints
  headingId: string
  now: number
}) {
  const i18n = useI18n()
  const { t } = i18n
  const { source, destination } = endpoints
  return (
    <div className="rule-summary">
      <h2 className="sr-only" id={headingId}>
        {t("rules.list.ruleName", { source: source.name, destination: destination.name })}
      </h2>
      <div className="rule-direction">
        <RuleEndpoint
          account={source.account}
          endpoint={rule.source}
          calendars={source.calendars}
          role="Source"
        />
        <ArrowRight aria-hidden="true" />
        <RuleEndpoint
          account={destination.account}
          endpoint={rule.destination}
          calendars={destination.calendars}
          role="Destination"
        />
      </div>
      <p className="rule-policy">
        <span>{t(POLICY_SUMMARY_KEYS[rule.privacy_policy][rule.sync_all_day_events ? "allDay" : "timedOnly"])}</span>
        <span className="rule-run" data-failed={rule.last_sync?.succeeded === false || undefined}>
          {rule.last_sync?.succeeded === false && <ShieldAlert aria-hidden="true" />}
          {lastRunLabel(i18n, rule.last_sync, now)}
        </span>
      </p>
    </div>
  )
}

function RuleNotes({
  rule,
  endpoints,
  state,
  stopped,
  work,
  feedback,
  previewId,
}: {
  rule: RuleSummary
  endpoints: RuleEndpoints
  state: string
  stopped: boolean
  work: RuleWork | null
  feedback: RuleFeedback | undefined
  previewId: string
}) {
  const { t, format } = useI18n()
  const { source, destination, disconnected } = endpoints
  return (
    <>
      {rule.reprojection_required && ["draft", "paused", "degraded"].includes(rule.state) && (
        <p className="rule-note">{t("rules.list.reprojectionRequired")}</p>
      )}
      {stopped && (
        <p className="rule-note">
          {disconnected.length > 0
            ? t("rules.list.stoppedDisconnected", { accounts: format.list(disconnected.map((account) => account.email)) })
            : t("rules.list.stoppedGeneric")}
        </p>
      )}
      {state === "dry_run_validated" && (
        <PreviewReadyNote id={previewId} preview={rule.latest_preview} destination={destination.name} />
      )}
      {work ? (
        <RuleWorkNote work={work} source={source.name} destination={destination.name} />
      ) : (
        <RuleFeedbackNote feedback={feedback} />
      )}
    </>
  )
}
