import { useQuery } from "@tanstack/react-query"
import {
  ArrowRight,
  CalendarDays,
  Check,
  CheckCircle2,
  ExternalLink,
  KeyRound,
} from "lucide-react"

import { AccountAvatar } from "@/components/account-avatar"
import { ChangeSign } from "@/components/change-sign"
import { GhostMark, type GhostExpression } from "@/components/ghost-mark"
import { LoadFailure } from "@/components/load-failure"
import { PageSkeleton } from "@/components/page-skeleton"
import { RuleStatusBadge } from "@/components/rule-commands"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { GoogleReturnHelp } from "@/features/settings"
import { EventWhen, HappenedLine } from "@/components/activity-event"
import {
  eventCell,
  formatClockTime,
  formatRunTime,
  whatHappened,
  type Happened,
} from "@/lib/activity"
import { activitySearch } from "@/lib/activity-location"
import { api, type Dashboard, type Incident, type RecentChange, type RuleSummary } from "@/lib/api"
import {
  appPathForRule,
  appPathForView,
  isPlainLeftClick,
  type OpenRule,
  type ViewChange,
} from "@/lib/navigation"
import { recordAuthorizationStart } from "@/lib/oauth-redirect"
import {
  overviewHealth,
  overviewRules,
  withoutRunningRemovals,
  type HealthAction,
  type OverviewTone,
  type RuleProblem,
} from "@/lib/overview-health"
import { overviewHeroCallouts } from "@/lib/overview-hero"
import { plural } from "@/lib/rule-change"
import { relativeTime } from "@/lib/relative-time"
import { useRemovingRuleIds } from "@/lib/rule-removal"
import { lastRunLabel } from "@/lib/rule-run"
import { ruleWork, workRefreshInterval } from "@/lib/rule-work"
import { useNow } from "@/lib/use-now"
import { useRuleEndpoints, type RuleEndpoints } from "@/lib/use-rule-endpoints"
import { cn } from "@/lib/utils"

const REFRESH_INTERVAL = 60_000
const GHOST_EXPRESSIONS: Record<OverviewTone, GhostExpression> = {
  healthy: "happy",
  review: "concerned",
  stopped: "crying",
  waiting: "neutral",
  paused: "sleepy",
  setup: "neutral",
}
// Where successive calls for help appear around the ghost, so they read as calling out.
const CALLOUT_POSITIONS = ["beside", "above", "below", "above-left"] as const

function healthActionPath(action: HealthAction): string {
  return action.ruleId ? appPathForRule(action.ruleId) : `${appPathForView(action.view)}${action.search ?? ""}`
}
const OVERVIEW_RULE_LIMIT = 6
const RECENT_CHANGE_LIMIT = 5

type Endpoints = (rule: Pick<RuleSummary, "source" | "destination">) => RuleEndpoints

function ruleName(endpoints: RuleEndpoints): string {
  return `${endpoints.source.name} → ${endpoints.destination.name}`
}

// Incident summaries are written with or without a closing period.
function sentence(text: string): string {
  return /[.!?]$/.test(text) ? text : `${text}.`
}

// Google failures a later attempt resolves; the rule keeps retrying without the administrator.
const WAITING_CATEGORIES = new Set(["rate_limit", "temporary"])

/**
 * The problems the Overview names by rule: stopped rules, then open incidents on running ones.
 * Blocked-event incidents are left out because the dashboard's blocked events already cover them.
 */
function ruleProblems(
  rules: RuleSummary[],
  incidents: Incident[] | undefined,
  endpoints: Endpoints,
  now: number,
): RuleProblem[] {
  const open = (incidents ?? []).filter((item) => item.state === "open")
  const since = (incident: Incident) =>
    `${sentence(incident.summary)} First seen ${relativeTime(incident.opened_at, now)}.`
  return rules.flatMap((rule): RuleProblem[] => {
    const name = ruleName(endpoints(rule))
    const incident = open.find((item) => item.rule_id === rule.id)
    if (rule.state === "degraded" || endpoints(rule).disconnected.length > 0) {
      const detail = incident ? since(incident) : `${lastRunLabel(rule.last_sync, now)}.`
      return [{ ruleId: rule.id, name, detail, kind: "stopped" }]
    }
    if (!incident || incident.category === "conflict") return []
    const kind = WAITING_CATEGORIES.has(incident.category) ? "waiting" : "review"
    return [{ ruleId: rule.id, name, detail: since(incident), kind }]
  })
}

export function OverviewView({ onViewChange, onOpenRule }: { onViewChange: ViewChange; onOpenRule: OpenRule }) {
  const now = useNow()
  const dashboard = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard, refetchInterval: REFRESH_INTERVAL })
  const rules = useQuery({
    queryKey: ["rules"],
    queryFn: api.rules,
    refetchInterval: (query) => workRefreshInterval(query.state.data, REFRESH_INTERVAL),
  })
  const google = useQuery({ queryKey: ["google-configuration"], queryFn: api.googleConfiguration })
  const incidents = useQuery({
    queryKey: ["incidents"],
    queryFn: api.incidents,
    enabled: (dashboard.data?.open_incidents ?? 0) > 0,
  })
  const { endpoints } = useRuleEndpoints(rules.data ?? [])
  const removingIds = useRemovingRuleIds(rules.data)

  if (dashboard.isPending || rules.isPending || google.isPending) return <PageSkeleton label="Loading overview" />
  if (dashboard.error || rules.error || google.error) return <LoadFailure title="Calendar Ghost could not load" />

  const health = overviewHealth(
    withoutRunningRemovals(dashboard.data, rules.data, removingIds),
    now,
    ruleProblems(rules.data.filter((rule) => !removingIds.has(rule.id)), incidents.data, endpoints, now),
  )
  const callouts = overviewHeroCallouts(health.tone)
  const followAction = (action: HealthAction) => (event: React.MouseEvent) => {
    if (!isPlainLeftClick(event)) return
    event.preventDefault()
    if (action.ruleId) onOpenRule(action.ruleId)
    else onViewChange(action.view, action.search ? { search: action.search } : undefined)
  }

  return (
    <div className="page-section overview-page">
      <section className="health-hero" data-tone={health.tone} aria-labelledby="health-title">
        <div className="health-hero-copy">
          <h1 id="health-title">{health.headline}</h1>
          {health.title && <p className="health-hero-context">{health.title}</p>}
          <p className="health-hero-detail">{health.detail}</p>
          {health.facts.length > 0 && (
            <ul className="health-hero-facts" aria-label="Synchronization summary">
              {health.facts.map((fact, index) => (
                <li key={fact}>
                  {index === 0 && health.tone === "healthy" && <CheckCircle2 aria-hidden="true" />}
                  {fact}
                </li>
              ))}
            </ul>
          )}
          {health.action && health.tone !== "setup" && (
            <Button className="health-hero-action" asChild>
              <a href={healthActionPath(health.action)} onClick={followAction(health.action)}>
                {health.action.label} <ArrowRight aria-hidden="true" />
              </a>
            </Button>
          )}
          {health.others.length > 0 && (
            <div className="health-hero-others">
              <h2>Also</h2>
              <ul>
                {health.others.map((other) => (
                  <li key={other.summary} data-tone={other.tone}>
                    <span>{other.summary}</span>
                    {other.action && (
                      <a className="text-link" href={healthActionPath(other.action)} onClick={followAction(other.action)}>
                        {other.action.label} <ArrowRight aria-hidden="true" />
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
        <div className="health-hero-visual" aria-hidden="true">
          <div className="health-hero-character">
            <div className="health-hero-halo" />
            <div className="health-hero-sparks">
              <span className="health-hero-spark health-hero-spark-ray health-hero-spark-ray-one" />
              <span className="health-hero-spark health-hero-spark-ray health-hero-spark-ray-two" />
              <span className="health-hero-spark health-hero-spark-ray health-hero-spark-ray-three" />
              <span className="health-hero-spark health-hero-spark-dot health-hero-spark-dot-one" />
              <span className="health-hero-spark health-hero-spark-dot health-hero-spark-dot-two" />
              <span className="health-hero-spark health-hero-spark-dot health-hero-spark-dot-three" />
              <span className="health-hero-spark health-hero-spark-dot health-hero-spark-dot-four" />
            </div>
            <GhostMark className="health-hero-ghost" expression={GHOST_EXPRESSIONS[health.tone]} />
            <div className="health-hero-callouts" data-calling={callouts.length > 1 ? "" : undefined}>
              {callouts.map((callout, index) => (
                <div
                  key={callout.title}
                  className="health-hero-callout"
                  data-position={CALLOUT_POSITIONS[index % CALLOUT_POSITIONS.length]}
                  style={{ "--call-index": index, "--call-count": callouts.length } as React.CSSProperties}
                >
                  <strong>{callout.title}</strong>
                  {callout.detail && <span>{callout.detail}</span>}
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {health.tone === "setup" && (
        <OnboardingSteps
          dashboard={dashboard.data}
          googleConfigured={google.data.configured}
          redirectUri={google.data.redirect_uri}
          onViewChange={onViewChange}
        />
      )}
      {rules.data.length > 0 && (
        <OverviewRules rules={rules.data} endpoints={endpoints} now={now} onViewChange={onViewChange} onOpenRule={onOpenRule} />
      )}
      {rules.data.some((rule) => rule.state === "enabled" || rule.last_sync) && (
        <RecentChanges rules={rules.data} endpoints={endpoints} now={now} onViewChange={onViewChange} onOpenRule={onOpenRule} />
      )}
    </div>
  )
}

function SectionLink({ href, onClick, children }: { href: string; onClick: () => void; children: string }) {
  return (
    <a
      className="text-link"
      href={href}
      onClick={(event) => {
        if (!isPlainLeftClick(event)) return
        event.preventDefault()
        onClick()
      }}
    >
      {children} <ArrowRight aria-hidden="true" />
    </a>
  )
}

function RecentChanges({
  rules,
  endpoints,
  now,
  onViewChange,
  onOpenRule,
}: {
  rules: RuleSummary[]
  endpoints: Endpoints
  now: number
  onViewChange: ViewChange
  onOpenRule: OpenRule
}) {
  const changes = useQuery({
    queryKey: ["recent-changes"],
    queryFn: () => api.recentChanges(RECENT_CHANGE_LIMIT),
    refetchInterval: REFRESH_INTERVAL,
  })
  const rulesById = new Map(rules.map((rule) => [rule.id, rule]))
  const lastCheck = rules
    .map((rule) => rule.last_sync?.completed_at)
    .filter((value): value is string => Boolean(value))
    .sort()
    .at(-1)

  return (
    <section className="workflow dashboard-card" aria-labelledby="recent-title">
      <div className="section-heading section-heading-inline">
        <div>
          <h2 id="recent-title">Recent changes</h2>
          <p>Latest sync events and changes.</p>
        </div>
        <SectionLink href={appPathForView("activity")} onClick={() => onViewChange("activity")}>
          All activity
        </SectionLink>
      </div>
      {changes.isPending ? (
        <div className="recent-loading" role="status" aria-label="Loading recent changes">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      ) : changes.error ? (
        <p className="empty-line">Recent changes could not load. Activity still has the full history.</p>
      ) : changes.data.length === 0 ? (
        <p className="empty-line">
          {lastCheck
            ? `No events changed recently. Calendar Ghost last checked ${relativeTime(lastCheck, now)}.`
            : "The first sync runs within five minutes. Changes will appear here."}
        </p>
      ) : (
        <ol className="recent-changes">
          {changes.data.map((change) => {
            const rule = rulesById.get(change.entry.rule_id)
            return (
              <RecentChangeItem
                key={change.entry.id}
                change={change}
                rule={rule}
                endpoints={rule ? endpoints(rule) : null}
                now={now}
                onViewChange={onViewChange}
                onOpenRule={onOpenRule}
              />
            )
          })}
        </ol>
      )}
    </section>
  )
}

// The marker shows what a change did to the destination calendar with the same sign Activity uses,
// so the line beside it carries only words.
function ChangeMarker({ happened }: { happened: Happened }) {
  return (
    <span className="recent-change-marker" data-tone={happened.tone}>
      <CalendarDays aria-hidden="true" />
      <span className="recent-change-sign" data-mark={happened.mark}>
        <ChangeSign mark={happened.mark} />
      </span>
    </span>
  )
}

function RecentChangeItem({
  change,
  rule,
  endpoints,
  now,
  onViewChange,
  onOpenRule,
}: {
  change: RecentChange
  rule: RuleSummary | undefined
  endpoints: RuleEndpoints | null
  now: number
  onViewChange: ViewChange
  onOpenRule: OpenRule
}) {
  const names = endpoints ? { source: endpoints.source.name, destination: endpoints.destination.name } : null
  // A collapsed repeat says how often instead of "again".
  const entry = change.repeats > 1 ? { ...change.entry, repeated: false } : change.entry
  const cell = eventCell(entry, names)
  const happened = whatHappened(entry, names)
  const since = new Date(change.first_occurred_at).toDateString() === new Date(now).toDateString()
    ? formatClockTime(change.first_occurred_at)
    : formatRunTime(change.first_occurred_at, new Date(now))
  const search = activitySearch({ ruleId: entry.rule_id, show: "", entryId: entry.id })
  return (
    <li className="recent-change-item">
      <ChangeMarker happened={happened} />
      <time dateTime={entry.occurred_at} title={new Date(entry.occurred_at).toLocaleString()}>
        {relativeTime(entry.occurred_at, now)}
      </time>
      <div className="recent-change-body">
        <a
          className="recent-change-event"
          href={`${appPathForView("activity")}${search}`}
          onClick={(event) => {
            if (!isPlainLeftClick(event)) return
            event.preventDefault()
            onViewChange("activity", { search })
          }}
        >
          {cell.state === "event" ? cell.title : cell.label}
        </a>
        {cell.state === "event" ? <EventWhen cell={cell} /> : cell.note && <span className="activity-event-when">{cell.note}</span>}
        <HappenedLine happened={happened} signed={false} suffix={change.repeats > 1 ? `${change.repeats} times since ${since}` : undefined} />
        {rule && endpoints ? (
          <a
            className="recent-change-rule"
            href={appPathForRule(rule.id)}
            onClick={(event) => {
              if (!isPlainLeftClick(event)) return
              event.preventDefault()
              onOpenRule(rule.id)
            }}
          >
            {endpoints.source.name} <ArrowRight aria-hidden="true" />
            <span className="sr-only"> to </span> {endpoints.destination.name}
          </a>
        ) : (
          <span className="recent-change-rule">Removed rule</span>
        )}
      </div>
    </li>
  )
}

function OverviewRules({
  rules,
  endpoints,
  now,
  onViewChange,
  onOpenRule,
}: {
  rules: RuleSummary[]
  endpoints: Endpoints
  now: number
  onViewChange: ViewChange
  onOpenRule: OpenRule
}) {
  const removingIds = useRemovingRuleIds(rules)
  const shown = overviewRules(rules, removingIds, OVERVIEW_RULE_LIMIT)
  return (
    <section className="workflow dashboard-card" aria-labelledby="overview-rules-title">
      <div className="section-heading section-heading-inline">
        <div>
          <h2 id="overview-rules-title">Rules</h2>
          <p>{rules.every((rule) => rule.state === "enabled") ? plural(rules.length, "active rule") : `${plural(rules.length, "rule")} configured`}</p>
        </div>
        <SectionLink href={appPathForView("rules")} onClick={() => onViewChange("rules")}>
          {rules.length > shown.length ? `All ${rules.length} rules` : "Manage rules"}
        </SectionLink>
      </div>
      <ul className="overview-rules">
        {shown.map((rule) => {
          const { source, destination, disconnected } = endpoints(rule)
          const stopped = rule.state === "degraded" || disconnected.length > 0
          const removing = removingIds.has(rule.id)
          const work = ruleWork({ pending: undefined, running: rule.running, removing })
          const content = (
            <>
              <span className="overview-rule-name">
                <OverviewEndpoint endpoint={source} accountId={rule.source.connected_account_id} />
                <ArrowRight aria-hidden="true" />
                <span className="sr-only"> to </span>
                <OverviewEndpoint endpoint={destination} accountId={rule.destination.connected_account_id} />
              </span>
              <span className="overview-rule-run">
                {rule.state === "enabled" || stopped ? lastRunLabel(rule.last_sync, now) : "Not running"}
              </span>
            </>
          )
          return (
            <li key={rule.id}>
              <a
                href={appPathForRule(rule.id)}
                onClick={(event) => {
                  if (!isPlainLeftClick(event)) return
                  event.preventDefault()
                  onOpenRule(rule.id)
                }}
              >
                <span className="overview-rule-link">{content}</span>
              </a>
              <RuleStatusBadge state={removing ? "removing" : rule.state} stopped={stopped} working={work?.kind} />
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function OverviewEndpoint({ endpoint, accountId }: { endpoint: RuleEndpoints["source"]; accountId: string }) {
  return (
    <span className="overview-rule-endpoint" title={endpoint.account?.email ?? accountId}>
      <AccountAvatar
        displayName={endpoint.account?.display_name ?? ""}
        email={endpoint.account?.email ?? accountId}
        avatarUrl={endpoint.account?.avatar_url}
        compact
      />
      <span>{endpoint.name}</span>
    </span>
  )
}

function OnboardingSteps({
  dashboard,
  googleConfigured,
  redirectUri,
  onViewChange,
}: {
  dashboard: Dashboard
  googleConfigured: boolean
  redirectUri: string | null
  onViewChange: ViewChange
}) {
  // Only an authorized account lets the next step work; a disconnected one must be renewed first.
  const reauthorize = dashboard.connected_accounts === 0 && dashboard.disconnected_accounts > 0
  const done = [dashboard.connected_accounts > 0, dashboard.sync_rules > 0, dashboard.enabled_rules > 0]
  const current = done.indexOf(false)
  const rulesLink = (label: string, createRule: boolean) => (
    <Button asChild>
      <a
        href={appPathForView("rules")}
        onClick={(event) => {
          if (!isPlainLeftClick(event)) return
          event.preventDefault()
          onViewChange("rules", { createRule })
        }}
      >
        {label} <ArrowRight aria-hidden="true" />
      </a>
    </Button>
  )
  const steps = [
    reauthorize ? {
      title: "Reauthorize your Google account",
      body: "Its access was removed or expired. Renew it in Settings before creating a rule.",
      action: (
        <Button asChild>
          <a
            href={appPathForView("settings")}
            onClick={(event) => {
              if (!isPlainLeftClick(event)) return
              event.preventDefault()
              onViewChange("settings")
            }}
          >
            Reauthorize in Settings <ArrowRight aria-hidden="true" />
          </a>
        </Button>
      ),
    } : {
      title: "Connect a Google account",
      body: "Authorize calendar discovery and event access for one Google account.",
      action: (
        <div className="step-action">
          <Button disabled={!googleConfigured} onClick={() => {
              recordAuthorizationStart()
              window.location.assign("/api/v1/oauth/google/start")
            }}>
            <KeyRound aria-hidden="true" /> Connect Google account <ExternalLink aria-hidden="true" />
          </Button>
          {!googleConfigured && (
            <p className="configuration-note">
              Add the master key and Google OAuth credentials in <code>.env</code>, then restart.
            </p>
          )}
        </div>
      ),
    },
    {
      title: "Create a rule",
      body: "Choose one source calendar, one destination calendar, and what the destination may show.",
      action: rulesLink("Create a rule", true),
    },
    {
      title: "Preview and start syncing",
      body: "Review exactly what will be written before the first event reaches the destination.",
      action: rulesLink("Review rules", false),
    },
  ]
  return (
    <section className="workflow dashboard-card setup-card" aria-labelledby="workflow-title">
      <div className="section-heading">
        <div>
          <h2 id="workflow-title">Getting started</h2>
          <p>Nothing is written to Google until a rule passes preview and you start it.</p>
        </div>
        <span className="step-progress">Step {current + 1} of 3</span>
      </div>
      {current === 0 && <GoogleReturnHelp redirectUri={redirectUri} />}
      <ol className="step-list">
        {steps.map((step, index) => (
          <li
            key={step.title}
            className={cn("step-row", done[index] ? "done" : index === current ? "current" : "pending")}
            aria-current={index === current ? "step" : undefined}
          >
            <span className="step-number">
              {done[index] && <span className="sr-only">Done: </span>}
              {done[index] ? <Check aria-hidden="true" /> : index + 1}
            </span>
            <div className="step-content">
              <div><h3>{step.title}</h3><p>{step.body}</p></div>
              {index === current && step.action}
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}
