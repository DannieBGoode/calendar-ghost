import { ArrowRight, type LucideIcon } from "lucide-react"
import type { ReactNode } from "react"

import { LearnWhyLink } from "@/components/learn-why-link"
import { RULE_SETTING_ICONS } from "@/components/rule-setting-icons"
import { useI18n } from "@/i18n/provider"
import type { RuleDetail, RunOutcome } from "@/lib/api"
import { ruleCadence } from "@/lib/instant-sync"
import { tentativeFact, unansweredFact } from "@/lib/invitation-responses"
import { activitySearch, appPathForView, isPlainLeftClick, type ViewChange } from "@/lib/navigation"
import { runOutcomeSummary } from "@/lib/rule-change"

/** One choice of the rule, beside the icon Rule Preview shows for the same choice. */
function SettingFact({ icon: Icon, label, children }: { icon: LucideIcon; label: string; children: ReactNode }) {
  return (
    <div>
      <dt>
        <Icon aria-hidden="true" />
        {label}
      </dt>
      <dd>{children}</dd>
    </div>
  )
}

/**
 * The rule's choices in two groups, as its policy form groups them: how events look, then which
 * events it includes. Rule Preview lists them in the same order.
 */
export function RuleFacts({ detail }: { detail: RuleDetail }) {
  const i18n = useI18n()
  const { t } = i18n
  const icons = RULE_SETTING_ICONS
  return (
    <section className="rule-section page-card" aria-labelledby="rule-facts-title">
      <h2 id="rule-facts-title">{t("ruleDetails.facts.title")}</h2>
      <div className="rule-facts-groups">
        <dl className="rule-facts rule-facts-iconed">
          <SettingFact icon={icons.eventInformation} label={t("ruleDetails.facts.eventInformation")}>
            {detail.privacy_policy === "busy_only" ? t("ruleDetails.facts.busyOnly") : t("ruleDetails.facts.copyDetails")}
          </SettingFact>
          <SettingFact icon={icons.tentative} label={t("ruleDetails.facts.tentative")}>
            {tentativeFact(i18n, detail)}
          </SettingFact>
          <SettingFact icon={icons.unanswered} label={t("ruleDetails.facts.unanswered")}>
            {unansweredFact(i18n, detail)}
          </SettingFact>
          <SettingFact icon={icons.declined} label={t("ruleDetails.facts.declined")}>
            {t("ruleDetails.facts.declinedValue")}
          </SettingFact>
        </dl>
        <dl className="rule-facts rule-facts-iconed">
          <SettingFact icon={icons.allDay} label={t("ruleDetails.facts.allDay")}>
            {detail.sync_all_day_events ? t("ruleDetails.facts.allDayIncluded") : t("ruleDetails.facts.allDayExcluded")}
          </SettingFact>
          <SettingFact icon={icons.birthdays} label={t("ruleDetails.facts.birthdays")}>
            {detail.sync_birthdays ? t("ruleDetails.facts.birthdaysIncluded") : t("ruleDetails.facts.birthdaysExcluded")}
          </SettingFact>
          <SettingFact icon={icons.startingPoint} label={t("ruleDetails.facts.startingPoint")}>
            {t("ruleDetails.facts.startingPointValue", { count: detail.initial_lookback_days })}
          </SettingFact>
        </dl>
      </div>
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
        <ProjectionsFact detail={detail} sourceName={sourceName} destinationName={destinationName} />
      </dl>
    </section>
  )
}

/** How many events the rule keeps in its destination, the ones every run and check looks after. */
function ProjectionsFact({
  detail,
  sourceName,
  destinationName,
}: {
  detail: RuleDetail
  sourceName: string
  destinationName: string
}) {
  const { t } = useI18n()
  const words = { count: detail.mapping_count, source: sourceName, destination: destinationName }
  return (
    <div>
      <dt>{t("ruleDetails.runs.projections")}</dt>
      <dd>
        {detail.mapping_count === 0 ? t("ruleDetails.runs.projectionsNone", words) : t("ruleDetails.runs.projectionsValue", words)}
        <span className="rule-fact-explanation">{t("ruleDetails.runs.projectionsExplanation", words)}</span>
      </dd>
    </div>
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
