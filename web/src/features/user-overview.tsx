import { Badge } from "@/components/ui/badge"
import { useI18n } from "@/i18n/provider"
import type { ResourceUse, UserOverview } from "@/lib/api"
import { problemText, resourceFacts, verdictTone } from "@/lib/operator-overview"
import { ruleStateLabel } from "@/lib/rule-change"
import { useNow } from "@/lib/use-now"

type Status = UserOverview["status"]
type HeadingLevel = 2 | 3

/**
 * What the Operator Overview shows about one User: their verdict, problems, and rules, with
 * calendars only as "Calendar 1", "Calendar 2", and their resource use. People shows it to an
 * administrator and Settings shows the same to that User, so both always see the same.
 */
export function UserOverviewDetails({ overview, headingLevel }: { overview: UserOverview; headingLevel: HeadingLevel }) {
  const now = useNow()
  return (
    <div className="user-overview">
      <VerdictBlock status={overview.status} now={now} />
      <ProblemsBlock status={overview.status} now={now} headingLevel={headingLevel} />
      <RulesBlock status={overview.status} now={now} headingLevel={headingLevel} />
      <ResourcesBlock resources={overview.resources} headingLevel={headingLevel} />
    </div>
  )
}

function Heading({ level, children }: { level: HeadingLevel; children: string }) {
  return level === 2 ? <h2>{children}</h2> : <h3>{children}</h3>
}

function VerdictBlock({ status, now }: { status: Status; now: number }) {
  const i18n = useI18n()
  const { t } = i18n
  return (
    <div className="user-overview-verdict">
      <Badge variant={verdictTone(status.status)}>{t(`people.verdicts.${status.status}`)}</Badge>
      <p>{t(`people.overview.verdict.${status.status}`)}</p>
      <p className="user-overview-muted">
        {status.last_synced_at
          ? t("people.overview.lastSync", { relative: i18n.format.relative(status.last_synced_at, now) })
          : t("people.overview.neverSynced")}
      </p>
    </div>
  )
}

function ProblemsBlock({ status, now, headingLevel }: { status: Status; now: number; headingLevel: HeadingLevel }) {
  const i18n = useI18n()
  const { t } = i18n
  if (status.problems.length === 0) return null
  const ruleName = new Map(status.rules.map((rule) => [rule.id, rule.name]))
  return (
    <div className="user-overview-block">
      <Heading level={headingLevel}>{t("people.overview.problemsTitle")}</Heading>
      <ul className="user-overview-list">
        {status.problems.map((problem) => (
          <li key={`${problem.kind}:${problem.rule_id ?? ""}:${problem.since ?? ""}:${problem.summary}`}>
            <span>
              {problem.rule_id && ruleName.has(problem.rule_id) && (
                <strong className="user-overview-rule">{ruleName.get(problem.rule_id)}</strong>
              )}
              {problemText(i18n, problem, status.counts.blocked_events)}
            </span>
            {problem.since && (
              <span className="user-overview-muted">
                {t("people.overview.since", { relative: i18n.format.relative(problem.since, now) })}
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

function RulesBlock({ status, now, headingLevel }: { status: Status; now: number; headingLevel: HeadingLevel }) {
  const i18n = useI18n()
  const { t } = i18n
  return (
    <div className="user-overview-block">
      <Heading level={headingLevel}>{t("people.overview.rulesTitle")}</Heading>
      {status.rules.length === 0 ? (
        <p className="user-overview-muted">{t("people.overview.noRules")}</p>
      ) : (
        <ul className="user-overview-list">
          {status.rules.map((rule) => (
            <li key={rule.id}>
              <span>
                <strong className="user-overview-rule">{rule.name}</strong>
                {ruleStateLabel(i18n, rule.state)}
              </span>
              <span className="user-overview-muted">
                {rule.last_succeeded_at
                  ? t("people.overview.lastSync", { relative: i18n.format.relative(rule.last_succeeded_at, now) })
                  : t("people.overview.neverSynced")}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function ResourcesBlock({ resources, headingLevel }: { resources: ResourceUse; headingLevel: HeadingLevel }) {
  const i18n = useI18n()
  const { t } = i18n
  const facts = resourceFacts(i18n, resources)
  const since = i18n.format.shortDay(resources.since, true)
  return (
    <div className="user-overview-block">
      <Heading level={headingLevel}>{t("people.overview.resourcesTitle")}</Heading>
      <p>{i18n.format.unitList(facts.kept)}</p>
      {facts.calls.length === 0 ? (
        <p className="user-overview-muted">{t("people.overview.noCalls", { since })}</p>
      ) : (
        <>
          <p className="user-overview-muted">{t("people.overview.callsTitle", { since })}</p>
          <ul className="user-overview-list">
            {facts.calls.map((calls) => (
              <li key={calls}>{calls}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
