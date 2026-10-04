import { useQuery } from "@tanstack/react-query"
import { ArrowRight, CalendarDays } from "lucide-react"

import { AccountAvatar } from "@/components/account-avatar"
import { EventWhen, HappenedLine } from "@/components/activity-event"
import { ChangeSign } from "@/components/change-sign"
import { RuleStatusBadge } from "@/components/rule-commands"
import { Skeleton } from "@/components/ui/skeleton"
import {
  eventCell,
  formatClockTime,
  formatRunTime,
  whatHappened,
  type Happened,
} from "@/lib/activity"
import { activitySearch } from "@/lib/activity-location"
import { api, type RecentChange, type RuleSummary } from "@/lib/api"
import {
  appPathForRule,
  appPathForView,
  isPlainLeftClick,
  type OpenRule,
  type ViewChange,
} from "@/lib/navigation"
import { overviewRules } from "@/lib/overview-health"
import { plural } from "@/lib/rule-change"
import { relativeTime } from "@/lib/relative-time"
import { useRemovingRuleIds } from "@/lib/rule-removal"
import { lastRunLabel } from "@/lib/rule-run"
import { ruleWork } from "@/lib/rule-work"
import type { RuleEndpoints } from "@/lib/use-rule-endpoints"

export const REFRESH_INTERVAL = 60_000
const OVERVIEW_RULE_LIMIT = 6
const RECENT_CHANGE_LIMIT = 5

export type Endpoints = (rule: Pick<RuleSummary, "source" | "destination">) => RuleEndpoints

type SectionProps = {
  rules: RuleSummary[]
  endpoints: Endpoints
  now: number
  onViewChange: ViewChange
  onOpenRule: OpenRule
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

export function RecentChanges({ rules, endpoints, now, onViewChange, onOpenRule }: SectionProps) {
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

export function OverviewRules({ rules, endpoints, now, onViewChange, onOpenRule }: SectionProps) {
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
