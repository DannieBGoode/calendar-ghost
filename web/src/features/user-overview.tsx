import { useId, type ReactNode } from "react"

import { RuleStatusBadge } from "@/components/rule-commands"
import { VerdictBadge } from "@/components/verdict-badge"
import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import type { ResourceUse, ServerProblem, UserOverview } from "@/lib/api"
import {
  calendarName,
  callsMeaning,
  nextStep,
  ownStepTarget,
  problemText,
  resourceFacts,
  type Audience,
} from "@/lib/operator-overview"

type Status = UserOverview["status"]
type StatusRule = Status["rules"][number]
type HeadingLevel = 2 | 3

/** Cards on a page of their own, such as a person's page under People. */
export const CARDS = "cards" as const
/** Rows inside one Settings group. */
export const ROWS = "rows" as const

/** Where the person themself goes to act on one of their own problems. */
export type OwnActions = {
  openRule: (ruleId: string) => void
  openConnections: () => void
  openActivity: (ruleId: string | null) => void
}

type Options = {
  now: number
  audience: Audience
  headingLevel: HeadingLevel
  /** Cards on a page of their own; rows inside one Settings group. */
  layout: typeof CARDS | typeof ROWS
  /** The person's own calendar names by number, shown beside each number for them only. */
  ownNames?: ReadonlyMap<number, string>
  /** Links to act on their own problems, for the person themself only. */
  actions?: OwnActions
}

/**
 * What the Operator Overview shows about one User: their sync health, then each rule with its
 * problem and who takes the next step, then their accounts, Activity, and calls. Calendars appear
 * only as "Calendar 1", "Calendar 2". People shows it to an administrator, and Settings shows the
 * same to that User, with their own names beside the numbers.
 */
export function UserOverviewDetails({ overview, ...options }: Options & { overview: UserOverview }) {
  const body = (
    <>
      <SyncBlock status={overview.status} options={options} />
      <UseBlock resources={overview.resources} options={options} />
    </>
  )
  return options.layout === CARDS ? (
    <div className="user-overview">{body}</div>
  ) : (
    <div className="user-overview settings-list">{body}</div>
  )
}

function Block({
  options,
  title,
  className,
  children,
}: {
  options: Options
  title: string
  className?: string
  children: ReactNode
}) {
  const id = useId()
  const heading = options.headingLevel === 2 ? <h2 id={id}>{title}</h2> : <h3 id={id}>{title}</h3>
  const kind = options.layout === CARDS ? "page-card workflow" : "setting-item"
  return (
    <section className={`${kind} user-overview-block ${className ?? ""}`} aria-labelledby={id}>
      {heading}
      {children}
    </section>
  )
}

/** A rule's name from its calendars: arrows for the eye, words for a screen reader. */
function RuleName({
  i18n,
  rule,
  ownNames,
}: {
  i18n: I18n
  rule: StatusRule
  ownNames?: ReadonlyMap<number, string> | undefined
}) {
  const names = {
    source: calendarName(i18n, rule.source, ownNames),
    destination: calendarName(i18n, rule.destination, ownNames),
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
  const byRule = new Map(status.problems.filter((p) => p.rule_id).map((p) => [p.rule_id, p]))
  const unattached = status.problems.filter((p) => !p.rule_id || !status.rules.some((rule) => rule.id === p.rule_id))
  return (
    <Block options={options} title={t("people.overview.statusTitle")} className="user-overview-health">
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
            <RuleItem key={rule.id} rule={rule} problem={byRule.get(rule.id)} status={status} options={options} />
          ))}
        </ul>
      )}
      {status.rules.length === 0 && <p className="user-overview-muted">{t("people.overview.noRules")}</p>}
    </Block>
  )
}

function RuleItem({
  rule,
  problem,
  status,
  options,
}: {
  rule: StatusRule
  problem: ServerProblem | undefined
  status: Status
  options: Options
}) {
  const i18n = useI18n()
  return (
    <li>
      <div className="user-overview-item-title">
        <RuleName i18n={i18n} rule={rule} ownNames={options.ownNames} />
        <RuleStatusBadge state={rule.state} stopped={rule.problem?.kind === "stopped"} />
      </div>
      <p className="user-overview-muted">{lastSync(i18n, rule.last_succeeded_at, options.now)}</p>
      {problem && <ProblemDetail problem={problem} status={status} options={options} />}
    </li>
  )
}

/** What went wrong, who takes the next step and how, and since when. */
function ProblemDetail({ problem, status, options }: { problem: ServerProblem; status: Status; options: Options }) {
  const i18n = useI18n()
  return (
    <div className="user-overview-problem">
      <p className="user-overview-problem-text">{problemText(i18n, problem, status.counts.blocked_events)}</p>
      <p className="user-overview-next">
        {nextStep(i18n, problem, options.audience)}
        {options.actions && <OwnStep problem={problem} actions={options.actions} />}
      </p>
      {problem.since && (
        <p className="user-overview-muted">
          {i18n.t("people.overview.since", { relative: i18n.format.relative(problem.since, options.now) })}
        </p>
      )}
    </div>
  )
}

/** The person's own way to the step: their rule, their Google connections, or their Activity. */
function OwnStep({ problem, actions }: { problem: ServerProblem; actions: OwnActions }) {
  const { t } = useI18n()
  const target = ownStepTarget(problem)
  if (target === null) return null
  const rule = problem.rule_id
  const open = {
    connections: actions.openConnections,
    rule: () => {
      if (rule) actions.openRule(rule)
    },
    activity: () => actions.openActivity(rule),
  }[target]
  return (
    <>
      {" "}
      <button type="button" className="text-link inline-link" onClick={open}>
        {t(`people.overview.go.${target}`)}
      </button>
    </>
  )
}

/** What the person keeps here and the calls their rules made, with one line on what the calls mean. */
function UseBlock({ resources, options }: { resources: ResourceUse; options: Options }) {
  const i18n = useI18n()
  const { t } = i18n
  const facts = resourceFacts(i18n, resources)
  const since = i18n.format.shortDay(resources.since, true)
  const meaning = callsMeaning(i18n, resources.provider_calls)
  return (
    <Block options={options} title={t("people.overview.resourcesTitle")}>
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
