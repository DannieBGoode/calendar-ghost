import { useQuery } from "@tanstack/react-query"
import {
  ArrowRight,
  CalendarDays,
  Check,
  CheckCircle2,
  CircleDot,
  ExternalLink,
  KeyRound,
  ShieldAlert,
} from "lucide-react"

import { AccountAvatar } from "@/components/account-avatar"
import { GhostMark } from "@/components/ghost-mark"
import { LoadFailure } from "@/components/load-failure"
import { PageSkeleton } from "@/components/page-skeleton"
import { RuleStatusBadge } from "@/components/rule-commands"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { GoogleReturnHelp } from "@/features/settings"
import { EventWhen, HappenedLine } from "@/components/activity-event"
import { eventCell, formatClockTime, formatRunTime, whatHappened } from "@/lib/activity"
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
  type AttentionRule,
  type OverviewTone,
} from "@/lib/overview-health"
import { plural } from "@/lib/rule-change"
import { relativeTime } from "@/lib/relative-time"
import { useRemovingRuleIds } from "@/lib/rule-removal"
import { lastRunLabel } from "@/lib/rule-run"
import { ruleWork, workRefreshInterval } from "@/lib/rule-work"
import { useNow } from "@/lib/use-now"
import { useRuleEndpoints, type RuleEndpoints } from "@/lib/use-rule-endpoints"
import { cn } from "@/lib/utils"

const REFRESH_INTERVAL = 60_000
const OVERVIEW_RULE_LIMIT = 6
const RECENT_CHANGE_LIMIT = 5

type Endpoints = (rule: Pick<RuleSummary, "source" | "destination">) => RuleEndpoints

function ruleName(endpoints: RuleEndpoints): string {
  return `${endpoints.source.name} → ${endpoints.destination.name}`
}

function attentionRule(
  rules: RuleSummary[],
  incidents: Incident[] | undefined,
  endpoints: Endpoints,
  now: number,
): AttentionRule | null {
  const byId = new Map(rules.map((rule) => [rule.id, rule]))
  const incident = incidents?.find((item) => item.state === "open" && item.rule_id && byId.has(item.rule_id))
  if (incident?.rule_id) {
    return {
      ruleId: incident.rule_id,
      name: ruleName(endpoints(byId.get(incident.rule_id)!)),
      detail: `${incident.summary} Since ${relativeTime(incident.opened_at, now)}.`,
    }
  }
  const stopped = rules.find((rule) => rule.state === "degraded" || endpoints(rule).disconnected.length > 0)
  if (!stopped) return null
  return { ruleId: stopped.id, name: ruleName(endpoints(stopped)), detail: `${lastRunLabel(stopped.last_sync, now)}.` }
}

function heroCallout(tone: OverviewTone): { title: string; detail: string } {
  if (tone === "healthy") return { title: "All good!", detail: "Your calendars are in sync." }
  if (tone === "attention") return { title: "Needs attention", detail: "Review the affected rule to continue." }
  return { title: "Ready when you are", detail: "Preview comes before anything is written." }
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
    attentionRule(rules.data.filter((rule) => !removingIds.has(rule.id)), incidents.data, endpoints, now),
  )
  const SignalIcon = health.tone === "attention" ? ShieldAlert : health.tone === "healthy" ? CheckCircle2 : CircleDot
  const action = health.action
  const callout = heroCallout(health.tone)
  const firstFact = dashboard.data.enabled_rules > 0
    ? `${plural(dashboard.data.enabled_rules, "rule")} running`
    : health.tone === "setup"
      ? "Setup in three steps"
      : "No rules running"
  const secondFact = dashboard.data.last_synced_at
    ? `Last sync ${relativeTime(dashboard.data.last_synced_at, now)}`
    : health.tone === "setup"
      ? "Nothing written yet"
      : "First sync within five minutes"

  return (
    <div className="page-section overview-page">
      <section className="health-hero" data-tone={health.tone} aria-labelledby="health-title">
        <div className="health-hero-copy">
          <div className="health-hero-status">
            <SignalIcon aria-hidden="true" />
            <span>{health.badge}</span>
          </div>
          <h1 id="health-title">{health.headline}</h1>
          <p className="health-hero-detail">{health.detail}</p>
          <div className="health-hero-facts" aria-label="Synchronization summary">
            <span><SignalIcon aria-hidden="true" /> {firstFact}</span>
            <span className="health-hero-separator" aria-hidden="true">•</span>
            <span>{secondFact}</span>
          </div>
          {action && health.tone !== "setup" && (
            <Button className="health-hero-action" asChild>
              <a
                href={action.ruleId ? appPathForRule(action.ruleId) : `${appPathForView(action.view)}${action.search ?? ""}`}
                onClick={(event) => {
                  if (!isPlainLeftClick(event)) return
                  event.preventDefault()
                  if (action.ruleId) onOpenRule(action.ruleId)
                  else onViewChange(action.view, action.search ? { search: action.search } : undefined)
                }}
              >
                {action.label} <ArrowRight aria-hidden="true" />
              </a>
            </Button>
          )}
        </div>
        <div className="health-hero-visual" aria-hidden="true">
          <div className="health-hero-halo" />
          <GhostMark className="health-hero-ghost" />
          <div className="health-hero-callout">
            <strong>{callout.title}</strong>
            <span>{callout.detail}</span>
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
          <p>Latest synchronization decisions and changes.</p>
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
  const markerTone = entry.event?.cancelled ? "cancelled" : happened.tone
  const since = new Date(change.first_occurred_at).toDateString() === new Date(now).toDateString()
    ? formatClockTime(change.first_occurred_at)
    : formatRunTime(change.first_occurred_at, new Date(now))
  const search = activitySearch({ ruleId: entry.rule_id, show: "", entryId: entry.id })
  return (
    <li className="recent-change-item">
      <span className="recent-change-marker" data-tone={markerTone}>
        <CalendarDays aria-hidden="true" />
      </span>
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
        <HappenedLine happened={happened} suffix={change.repeats > 1 ? `${change.repeats} times since ${since}` : undefined} />
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
          <p>{plural(rules.length, "rule")} configured</p>
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
                <span className="overview-rule-name">
                  <OverviewEndpoint endpoint={source} accountId={rule.source.connected_account_id} />
                  <ArrowRight aria-hidden="true" />
                  <span className="sr-only"> to </span>
                  <OverviewEndpoint endpoint={destination} accountId={rule.destination.connected_account_id} />
                </span>
                <span className="overview-rule-run">
                  {rule.state === "enabled" || stopped ? lastRunLabel(rule.last_sync, now) : "Not running"}
                </span>
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
