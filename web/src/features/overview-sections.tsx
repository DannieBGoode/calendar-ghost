import { useQuery } from "@tanstack/react-query"
import { ArrowRight, CalendarDays } from "lucide-react"

import { AccountAvatar } from "@/components/account-avatar"
import { EventWhen, HappenedLine } from "@/components/activity-event"
import { ChangeSign } from "@/components/change-sign"
import { RuleStatusBadge } from "@/components/rule-commands"
import { Skeleton } from "@/components/ui/skeleton"
import { useI18n } from "@/i18n/provider"
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
  const { t, format } = useI18n()
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
          <h2 id="recent-title">{t("overview.recentChanges.heading")}</h2>
          <p>{t("overview.recentChanges.subtitle")}</p>
        </div>
        <SectionLink href={appPathForView("activity")} onClick={() => onViewChange("activity")}>
          {t("overview.recentChanges.allActivity")}
        </SectionLink>
      </div>
      {changes.isPending ? (
        <div className="recent-loading" role="status" aria-label={t("overview.recentChanges.loadingLabel")}>
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      ) : changes.error ? (
        <p className="empty-line">{t("overview.recentChanges.loadError")}</p>
      ) : changes.data.length === 0 ? (
        <p className="empty-line">
          {lastCheck
            ? t("overview.recentChanges.emptyWithCheck", { relative: format.relative(lastCheck, now) })
            : t("overview.recentChanges.emptyNoCheck")}
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
  const i18n = useI18n()
  const { t, format } = i18n
  const names = endpoints ? { source: endpoints.source.name, destination: endpoints.destination.name } : null
  // A collapsed repeat says how often instead of "again".
  const entry = change.repeats > 1 ? { ...change.entry, repeated: false } : change.entry
  const cell = eventCell(i18n, entry, names)
  const happened = whatHappened(i18n, entry, names)
  const since = new Date(change.first_occurred_at).toDateString() === new Date(now).toDateString()
    ? formatClockTime(i18n, change.first_occurred_at)
    : formatRunTime(i18n, change.first_occurred_at, new Date(now))
  const search = activitySearch({ ruleId: entry.rule_id, show: "", entryId: entry.id })
  return (
    <li className="recent-change-item">
      <ChangeMarker happened={happened} />
      <time dateTime={entry.occurred_at} title={format.dateTime(entry.occurred_at)}>
        {format.relative(entry.occurred_at, now)}
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
        <HappenedLine
          happened={happened}
          signed={false}
          suffix={change.repeats > 1 ? t("overview.recentChanges.repeatedSince", { count: change.repeats, since }) : undefined}
        />
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
            {/* The arrow line is visual; screen readers hear one sentence instead of glued fragments. */}
            <span aria-hidden="true">{endpoints.source.name}</span>
            <ArrowRight aria-hidden="true" />
            <span aria-hidden="true">{endpoints.destination.name}</span>
            <span className="sr-only">
              {t("overview.ruleSpoken", { source: endpoints.source.name, destination: endpoints.destination.name })}
            </span>
          </a>
        ) : (
          <span className="recent-change-rule">{t("overview.recentChanges.removedRule")}</span>
        )}
      </div>
    </li>
  )
}

export function OverviewRules({ rules, endpoints, now, onViewChange, onOpenRule }: SectionProps) {
  const i18n = useI18n()
  const { t } = i18n
  const removingIds = useRemovingRuleIds(rules)
  const shown = overviewRules(rules, removingIds, OVERVIEW_RULE_LIMIT)
  return (
    <section className="workflow dashboard-card" aria-labelledby="overview-rules-title">
      <div className="section-heading section-heading-inline">
        <div>
          <h2 id="overview-rules-title">{t("overview.rules.heading")}</h2>
          <p>
            {rules.every((rule) => rule.state === "enabled")
              ? t("overview.rules.activeCount", { count: rules.length })
              : t("overview.rules.configuredCount", { count: rules.length })}
          </p>
        </div>
        <SectionLink href={appPathForView("rules")} onClick={() => onViewChange("rules")}>
          {rules.length > shown.length ? t("overview.rules.allRules", { count: rules.length }) : t("overview.rules.manageRules")}
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
                {/* The arrow line is visual; screen readers hear one sentence instead of glued fragments. */}
                <OverviewEndpoint endpoint={source} accountId={rule.source.connected_account_id} />
                <ArrowRight aria-hidden="true" />
                <OverviewEndpoint endpoint={destination} accountId={rule.destination.connected_account_id} />
                <span className="sr-only">
                  {t("overview.ruleSpoken", { source: source.name, destination: destination.name })}
                </span>
              </span>
              <span className="overview-rule-run">
                {rule.state === "enabled" || stopped ? lastRunLabel(i18n, rule.last_sync, now) : t("overview.rules.notRunning")}
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
    <span className="overview-rule-endpoint" title={endpoint.account?.email ?? accountId} aria-hidden="true">
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
