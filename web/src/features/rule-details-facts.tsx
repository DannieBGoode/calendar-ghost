import { ArrowRight } from "lucide-react"

import type { RuleDetail, RunOutcome } from "@/lib/api"
import { tentativeFact, unansweredFact } from "@/lib/invitation-responses"
import { activitySearch, appPathForView, isPlainLeftClick, type ViewChange } from "@/lib/navigation"
import { plural, runOutcomeSummary } from "@/lib/rule-change"
import { relativeTime } from "@/lib/relative-time"

export function RuleFacts({ detail, destinationName }: { detail: RuleDetail; destinationName: string }) {
  return (
    <section className="rule-section page-card" aria-labelledby="rule-facts-title">
      <h2 id="rule-facts-title">What this rule does</h2>
      <dl className="rule-facts">
        <div>
          <dt>Event information</dt>
          <dd>
            {detail.privacy_policy === "busy_only"
              ? "Busy only: titles, descriptions, and locations stay private"
              : "Title, description, and location are copied"}
          </dd>
        </div>
        <div>
          <dt>All-day events</dt>
          <dd>{detail.sync_all_day_events ? "Included" : "Excluded; timed events only"}</dd>
        </div>
        <div>
          <dt>Events you answered Maybe</dt>
          <dd>{tentativeFact(detail)}</dd>
        </div>
        <div>
          <dt>Invitations you haven't answered</dt>
          <dd>{unansweredFact(detail)}</dd>
        </div>
        <div>
          <dt>Declined events</dt>
          <dd>Not synced</dd>
        </div>
        <div>
          <dt>Starting point</dt>
          <dd>Includes events from the past {plural(detail.initial_lookback_days, "day")} onward</dd>
        </div>
        <div>
          <dt>Projections</dt>
          <dd>{plural(detail.mapping_count, "projection")} this rule manages in {destinationName}</dd>
        </div>
      </dl>
    </section>
  )
}

export function RuleRuns({
  detail,
  sourceName,
  destinationName,
  now,
  onViewChange,
}: {
  detail: RuleDetail
  sourceName: string
  destinationName: string
  now: number
  onViewChange: ViewChange
}) {
  return (
    <section className="rule-section page-card" aria-labelledby="rule-runs-title">
      <div className="section-heading section-heading-inline">
        <h2 id="rule-runs-title">Latest runs</h2>
        <a
          className="text-link"
          href={`${appPathForView("activity")}${activitySearch(detail.id)}`}
          onClick={(event) => {
            if (!isPlainLeftClick(event)) return
            event.preventDefault()
            onViewChange("activity", { search: activitySearch(detail.id) })
          }}
        >
          This rule's activity <ArrowRight aria-hidden="true" />
        </a>
      </div>
      <dl className="rule-facts">
        <OutcomeFact
          label="Last sync"
          explanation={`Applies changes made in ${sourceName} since the previous run. Runs every five minutes.`}
          outcome={detail.last_sync}
          kind="sync"
          now={now}
        />
        <OutcomeFact
          label="Last reconciliation"
          explanation={`Compares the events this rule wrote to ${destinationName} from the past ${plural(detail.initial_lookback_days, "day")} onward with their sources and reports any that differ, without changing them. Runs when you choose Reconcile now.`}
          outcome={detail.last_reconciliation}
          kind="reconciliation"
          now={now}
        />
      </dl>
    </section>
  )
}

function OutcomeFact({
  label,
  explanation,
  outcome,
  kind,
  now,
}: {
  label: string
  explanation: string
  outcome: RunOutcome | null
  kind: "sync" | "reconciliation"
  now: number
}) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        {runOutcomeSummary(outcome, kind)}
        {outcome && (
          <time
            dateTime={outcome.completed_at}
            className="rule-fact-time"
            title={new Date(outcome.completed_at).toLocaleString()}
          >
            {relativeTime(outcome.completed_at, now)}
          </time>
        )}
        <span className="rule-fact-explanation">{explanation}</span>
      </dd>
    </div>
  )
}
