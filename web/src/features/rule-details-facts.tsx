import { ArrowRight } from "lucide-react"

import { LearnWhyLink } from "@/components/learn-why-link"
import { useI18n } from "@/i18n/provider"
import type { RuleDetail, RunOutcome } from "@/lib/api"
import { ruleCadence } from "@/lib/instant-sync"
import { tentativeFact, unansweredFact } from "@/lib/invitation-responses"
import { activitySearch, appPathForView, isPlainLeftClick, type ViewChange } from "@/lib/navigation"
import { runOutcomeSummary } from "@/lib/rule-change"

export function RuleFacts({ detail, destinationName }: { detail: RuleDetail; destinationName: string }) {
  const i18n = useI18n()
  const { t } = i18n
  return (
    <section className="rule-section page-card" aria-labelledby="rule-facts-title">
      <h2 id="rule-facts-title">{t("ruleDetails.facts.title")}</h2>
      <dl className="rule-facts">
        <div>
          <dt>{t("ruleDetails.facts.eventInformation")}</dt>
          <dd>
            {detail.privacy_policy === "busy_only" ? t("ruleDetails.facts.busyOnly") : t("ruleDetails.facts.copyDetails")}
          </dd>
        </div>
        <div>
          <dt>{t("ruleDetails.facts.allDay")}</dt>
          <dd>{detail.sync_all_day_events ? t("ruleDetails.facts.allDayIncluded") : t("ruleDetails.facts.allDayExcluded")}</dd>
        </div>
        <div>
          <dt>{t("ruleDetails.facts.birthdays")}</dt>
          <dd>{detail.sync_birthdays ? t("ruleDetails.facts.birthdaysIncluded") : t("ruleDetails.facts.birthdaysExcluded")}</dd>
        </div>
        <div>
          <dt>{t("ruleDetails.facts.tentative")}</dt>
          <dd>{tentativeFact(i18n, detail)}</dd>
        </div>
        <div>
          <dt>{t("ruleDetails.facts.unanswered")}</dt>
          <dd>{unansweredFact(i18n, detail)}</dd>
        </div>
        <div>
          <dt>{t("ruleDetails.facts.declined")}</dt>
          <dd>{t("ruleDetails.facts.declinedValue")}</dd>
        </div>
        <div>
          <dt>{t("ruleDetails.facts.startingPoint")}</dt>
          <dd>{t("ruleDetails.facts.startingPointValue", { count: detail.initial_lookback_days })}</dd>
        </div>
        <div>
          <dt>{t("ruleDetails.facts.projections")}</dt>
          <dd>{t("ruleDetails.facts.projectionsValue", { count: detail.mapping_count, destination: destinationName })}</dd>
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
  const { t } = useI18n()
  return (
    <section className="rule-section page-card" aria-labelledby="rule-runs-title">
      <div className="section-heading section-heading-inline">
        <h2 id="rule-runs-title">{t("ruleDetails.runs.title")}</h2>
        <a
          className="text-link"
          href={`${appPathForView("activity")}${activitySearch(detail.id)}`}
          onClick={(event) => {
            if (!isPlainLeftClick(event)) return
            event.preventDefault()
            onViewChange("activity", { search: activitySearch(detail.id) })
          }}
        >
          {t("ruleDetails.runs.activityLink")} <ArrowRight aria-hidden="true" />
        </a>
      </div>
      <dl className="rule-facts">
        <CadenceFact detail={detail} sourceName={sourceName} />
        <OutcomeFact
          label={t("ruleDetails.runs.lastSync")}
          explanation={t("ruleDetails.runs.syncExplanation", { source: sourceName })}
          outcome={detail.last_sync}
          kind="sync"
          now={now}
        />
        <OutcomeFact
          label={t("ruleDetails.runs.lastReconciliation")}
          explanation={t("ruleDetails.runs.reconciliationExplanation", {
            count: detail.initial_lookback_days,
            destination: destinationName,
          })}
          outcome={detail.last_reconciliation}
          kind="reconciliation"
          now={now}
        />
      </dl>
    </section>
  )
}

/**
 * How soon an enabled rule syncs: soon after its provider reports a change in its source, or on its
 * schedule with the reason and, where the guide explains it, "Learn why".
 */
function CadenceFact({ detail, sourceName }: { detail: RuleDetail; sourceName: string }) {
  const { t } = useI18n()
  if (detail.state !== "enabled") return null
  const cadence = ruleCadence(detail)
  const words = { source: sourceName, count: cadence.minutes }
  return (
    <div>
      <dt>{t("ruleDetails.cadence.label")}</dt>
      <dd>
        {cadence.instant ? t("ruleDetails.cadence.instant") : t("ruleDetails.cadence.every", { count: cadence.minutes })}
        <span className="rule-fact-explanation">
          {cadence.instant && t("ruleDetails.cadence.instantExplanation", words)}
          {cadence.reason && t(`ruleDetails.cadence.reason.${cadence.reason}`, words)}
          {cadence.helpUrl && (
            <>
              {" "}
              <LearnWhyLink href={cadence.helpUrl} />
            </>
          )}
        </span>
      </dd>
    </div>
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
  const i18n = useI18n()
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        {runOutcomeSummary(i18n, outcome, kind)}
        {outcome && (
          <time
            dateTime={outcome.completed_at}
            className="rule-fact-time"
            title={i18n.format.dateTime(outcome.completed_at)}
          >
            {i18n.format.relative(outcome.completed_at, now)}
          </time>
        )}
        <span className="rule-fact-explanation">{explanation}</span>
      </dd>
    </div>
  )
}
