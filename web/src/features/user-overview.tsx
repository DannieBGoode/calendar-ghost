import { RuleStatusBadge } from "@/components/rule-commands"
import { VerdictBadge } from "@/components/verdict-badge"
import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import type { ResourceUse, ServerProblem, UserOverview } from "@/lib/api"
import { calendarName, nextStep, problemText, resourceFacts, type Audience } from "@/lib/operator-overview"

type Status = UserOverview["status"]
type StatusRule = Status["rules"][number]
type HeadingLevel = 2 | 3

/**
 * What the Operator Overview shows about one User: their sync health and problems first, each with
 * who acts on it, then their rules, with calendars only as "Calendar 1", "Calendar 2", then their
 * resource use. People shows it to an administrator and Settings shows the same to that User.
 */
export function UserOverviewDetails({
  overview,
  now,
  audience,
  headingLevel,
}: {
  overview: UserOverview
  now: number
  audience: Audience
  headingLevel: HeadingLevel
}) {
  return (
    <div className="user-overview">
      <HealthCard status={overview.status} now={now} audience={audience} headingLevel={headingLevel} />
      <RulesCard status={overview.status} now={now} headingLevel={headingLevel} />
      <ResourcesCard resources={overview.resources} headingLevel={headingLevel} />
    </div>
  )
}

function Heading({ level, id, children }: { level: HeadingLevel; id: string; children: string }) {
  return level === 2 ? <h2 id={id}>{children}</h2> : <h3 id={id}>{children}</h3>
}

/** A rule's name from its calendars: arrows for the eye, words for a screen reader. */
function RuleName({ i18n, rule }: { i18n: I18n; rule: StatusRule }) {
  const names = { source: calendarName(i18n, rule.source), destination: calendarName(i18n, rule.destination) }
  return (
    <strong className="user-overview-rule">
      <span aria-hidden="true">{i18n.t("overview.ruleName", names)}</span>
      <span className="sr-only">{i18n.t("overview.ruleSpoken", names)}</span>
    </strong>
  )
}

function lastSync(i18n: I18n, at: string | null, now: number): string {
  return at
    ? i18n.t("people.overview.lastSync", { relative: i18n.format.relative(at, now) })
    : i18n.t("people.overview.neverSynced")
}

function HealthCard({
  status,
  now,
  audience,
  headingLevel,
}: {
  status: Status
  now: number
  audience: Audience
  headingLevel: HeadingLevel
}) {
  const i18n = useI18n()
  const { t } = i18n
  const rules = new Map(status.rules.map((rule) => [rule.id, rule]))
  return (
    <section className="page-card workflow user-overview-health" aria-labelledby="user-overview-health">
      <Heading level={headingLevel} id="user-overview-health">
        {t("people.overview.statusTitle")}
      </Heading>
      <div className="user-overview-verdict">
        <VerdictBadge verdict={status.status} />
        <p>{t(`people.overview.verdict.${status.status}`)}</p>
      </div>
      <p className="user-overview-muted">{lastSync(i18n, status.last_synced_at, now)}</p>
      {status.problems.length > 0 && (
        <ul className="user-overview-list user-overview-problems" aria-label={t("people.overview.problemsTitle")}>
          {status.problems.map((problem) => (
            <ProblemItem
              key={`${problem.kind}:${problem.rule_id ?? ""}:${problem.since ?? ""}:${problem.summary}`}
              problem={problem}
              rule={problem.rule_id ? rules.get(problem.rule_id) : undefined}
              blockedEvents={status.counts.blocked_events}
              now={now}
              audience={audience}
            />
          ))}
        </ul>
      )}
    </section>
  )
}

function ProblemItem({
  problem,
  rule,
  blockedEvents,
  now,
  audience,
}: {
  problem: ServerProblem
  rule: StatusRule | undefined
  blockedEvents: number
  now: number
  audience: Audience
}) {
  const i18n = useI18n()
  return (
    <li>
      <div className="user-overview-item-title">
        {rule && <RuleName i18n={i18n} rule={rule} />}
        <span>{problemText(i18n, problem, blockedEvents)}</span>
      </div>
      <p className="user-overview-next">{nextStep(i18n, problem, audience)}</p>
      {problem.since && (
        <p className="user-overview-muted">
          {i18n.t("people.overview.since", { relative: i18n.format.relative(problem.since, now) })}
        </p>
      )}
    </li>
  )
}

function RulesCard({ status, now, headingLevel }: { status: Status; now: number; headingLevel: HeadingLevel }) {
  const i18n = useI18n()
  const { t } = i18n
  return (
    <section className="page-card workflow" aria-labelledby="user-overview-rules">
      <Heading level={headingLevel} id="user-overview-rules">
        {t("people.overview.rulesTitle")}
      </Heading>
      {status.rules.length === 0 ? (
        <p className="user-overview-muted">{t("people.overview.noRules")}</p>
      ) : (
        <ul className="user-overview-list">
          {status.rules.map((rule) => (
            <li key={rule.id}>
              <div className="user-overview-item-title">
                <RuleName i18n={i18n} rule={rule} />
                <RuleStatusBadge state={rule.state} stopped={rule.problem?.kind === "stopped"} />
              </div>
              <p className="user-overview-muted">{lastSync(i18n, rule.last_succeeded_at, now)}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function ResourcesCard({ resources, headingLevel }: { resources: ResourceUse; headingLevel: HeadingLevel }) {
  const i18n = useI18n()
  const { t } = i18n
  const facts = resourceFacts(i18n, resources)
  const since = i18n.format.shortDay(resources.since, true)
  return (
    <section className="page-card workflow" aria-labelledby="user-overview-resources">
      <Heading level={headingLevel} id="user-overview-resources">
        {t("people.overview.resourcesTitle")}
      </Heading>
      <p>{i18n.format.unitList(facts.kept)}</p>
      {facts.calls.length === 0 ? (
        <p className="user-overview-muted">{t("people.overview.noCalls", { since })}</p>
      ) : (
        <div>
          <p className="user-overview-muted">{t("people.overview.callsTitle", { since })}</p>
          <ul className="user-overview-list user-overview-calls">
            {facts.calls.map((calls) => (
              <li key={calls}>{calls}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
