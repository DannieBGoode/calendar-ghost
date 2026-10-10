import { useId, type ReactNode } from "react"

import { HowToFixLink } from "@/components/how-to-fix-link"
import { RuleStatusBadge } from "@/components/rule-commands"
import { VerdictBadge } from "@/components/verdict-badge"
import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import type { ResourceUse, ServerProblem, UserOverview } from "@/lib/api"
import { causeOf, causeText, howToFixUrl, retryTiming } from "@/lib/causes"
import { calendarName, callsMeaning, nextStep, problemText, resourceFacts, type Audience } from "@/lib/operator-overview"

type Status = UserOverview["status"]
type StatusRule = Status["rules"][number]
type Options = {
  now: number
  audience: Audience
}

/**
 * What the Operator Overview shows about one User, on their page under People: their sync health,
 * then each rule with its problem and who takes the next step, then their accounts, Activity, and
 * calls. Calendars appear only as "Calendar 1", "Calendar 2".
 */
export function UserOverviewDetails({ overview, ...options }: Options & { overview: UserOverview }) {
  return (
    <div className="user-overview">
      <SyncBlock status={overview.status} options={options} />
      <UseBlock resources={overview.resources} />
    </div>
  )
}

function Block({
  title,
  className,
  children,
}: {
  title: string
  className?: string
  children: ReactNode
}) {
  const id = useId()
  return (
    <section className={`page-card workflow user-overview-block ${className ?? ""}`} aria-labelledby={id}>
      <h2 id={id}>{title}</h2>
      {children}
    </section>
  )
}

/** A rule's name from its calendars: arrows for the eye, words for a screen reader. */
function RuleName({ i18n, rule }: { i18n: I18n; rule: StatusRule }) {
  const names = {
    source: calendarName(i18n, rule.source),
    destination: calendarName(i18n, rule.destination),
  }
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

/** The verdict, then every rule with its problem under it; a problem of no one rule comes first. */
function SyncBlock({ status, options }: { status: Status; options: Options }) {
  const i18n = useI18n()
  const { t } = i18n
  // A rule can have several problems at once, such as a lapsed account and blocked events.
  const byRule = new Map<string, ServerProblem[]>()
  for (const problem of status.problems) {
    if (problem.rule_id) byRule.set(problem.rule_id, [...(byRule.get(problem.rule_id) ?? []), problem])
  }
  const unattached = status.problems.filter((p) => !p.rule_id || !status.rules.some((rule) => rule.id === p.rule_id))
  return (
    <Block title={t("people.overview.statusTitle")} className="user-overview-health">
      <div className="user-overview-verdict">
        <VerdictBadge verdict={status.status} />
        <p>{t(`people.overview.verdict.${status.status}`)}</p>
      </div>
      {(unattached.length > 0 || status.rules.length > 0) && (
        <ul className="user-overview-list">
          {unattached.map((problem) => (
            <li key={`${problem.kind}:${problem.summary}`}>
              <ProblemDetail problem={problem} status={status} options={options} />
            </li>
          ))}
          {status.rules.map((rule) => (
            <RuleItem key={rule.id} rule={rule} problems={byRule.get(rule.id) ?? []} status={status} options={options} />
          ))}
        </ul>
      )}
      {status.rules.length === 0 && <p className="user-overview-muted">{t("people.overview.noRules")}</p>}
    </Block>
  )
}

function RuleItem({
  rule,
  problems,
  status,
  options,
}: {
  rule: StatusRule
  problems: ServerProblem[]
  status: Status
  options: Options
}) {
  const i18n = useI18n()
  return (
    <li>
      <div className="user-overview-item-title">
        <RuleName i18n={i18n} rule={rule} />
        <RuleStatusBadge state={rule.state} stopped={rule.problem?.kind === "stopped"} />
      </div>
      <p className="user-overview-muted">{lastSync(i18n, rule.last_succeeded_at, options.now)}</p>
      {problems.map((problem) => (
        <ProblemDetail key={`${problem.kind}:${problem.summary}`} problem={problem} status={status} options={options} />
      ))}
    </li>
  )
}

/** What went wrong and its likely cause, who takes the next step and how, and since when. */
function ProblemDetail({ problem, status, options }: { problem: ServerProblem; status: Status; options: Options }) {
  const i18n = useI18n()
  const cause = causeOf(problem)
  const timing = retryTiming(i18n, problem, status.scheduler.next_pass_at ?? null, options.now)
  return (
    <div className="user-overview-problem">
      <p className="user-overview-problem-text">{problemText(i18n, problem, status.counts.blocked_events)}</p>
      {cause && <p className="user-overview-muted">{causeText(i18n, cause)}</p>}
      <ProblemStep problem={problem} options={options} />
      {timing && <p className="user-overview-muted">{timing}</p>}
      {problem.since && (
        <p className="user-overview-muted">
          {i18n.t("people.overview.since", { relative: i18n.format.relative(problem.since, options.now) })}
        </p>
      )}
    </div>
  )
}

/** Who takes the next step and how; an administrator's Cause adds the guide's fix. */
function ProblemStep({ problem, options }: { problem: ServerProblem; options: Options }) {
  const i18n = useI18n()
  const fix = howToFixUrl(causeOf(problem))
  return (
    <p className="user-overview-next">
      {nextStep(i18n, problem, options.audience)}
      {fix && (
        <>
          {" "}
          <HowToFixLink href={fix} />
        </>
      )}
    </p>
  )
}

/** What the person keeps here and the calls their rules made, with one line on what the calls mean. */
function UseBlock({ resources }: { resources: ResourceUse }) {
  const i18n = useI18n()
  const { t } = i18n
  const facts = resourceFacts(i18n, resources)
  const since = i18n.format.shortDay(resources.since, true)
  const meaning = callsMeaning(i18n, resources.provider_calls)
  return (
    <Block title={t("people.overview.resourcesTitle")}>
      <p>{i18n.format.unitList(facts.kept)}</p>
      {facts.calls.length === 0 ? (
        <p className="user-overview-muted">{t("people.overview.noCalls", { since })}</p>
      ) : (
        <div>
          <p className="user-overview-muted">{t("people.overview.callsTitle", { since })}</p>
          <ul className="user-overview-calls">
            {facts.calls.map((calls) => (
              <li key={calls}>{calls}</li>
            ))}
          </ul>
          {meaning && <p className="user-overview-next">{meaning}</p>}
        </div>
      )}
    </Block>
  )
}
