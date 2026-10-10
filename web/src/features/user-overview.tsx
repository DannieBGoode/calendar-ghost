import { useId, type ReactNode } from "react"

import { RuleStatusBadge } from "@/components/rule-commands"
import { VerdictBadge } from "@/components/verdict-badge"
import { ProblemDetail, type OwnPage, type ProblemOptions } from "@/features/user-overview-problem"
import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import type { ResourceUse, ServerProblem, UserOverview } from "@/lib/api"
import {
  arrangeProblems,
  calendarName,
  callsMeaning,
  resourceFacts,
  rulesRunning,
  type SharedProblem,
} from "@/lib/operator-overview"

export type { OwnPage }

type Status = UserOverview["status"]
type StatusRule = Status["rules"][number]
type Options = ProblemOptions

/**
 * What the Operator Overview shows about one User, on their page under People: their sync health,
 * then each rule with its problem and who takes the next step, then their accounts, Activity, and
 * calls. Calendars appear only as "Calendar 1", "Calendar 2", except on an administrator's own
 * page. With nothing wrong, it is one card, and the use is a quiet part of it.
 */
export function UserOverviewDetails({ overview, ...options }: Options & { overview: UserOverview }) {
  const { t } = useI18n()
  const quiet = overview.status.problems.length === 0
  return (
    <div className="user-overview">
      <SyncBlock status={overview.status} options={options}>
        {quiet && <UseFacts resources={overview.resources} />}
      </SyncBlock>
      {!quiet && (
        <Block title={t("people.overview.resourcesTitle")}>
          <UseFacts resources={overview.resources} />
        </Block>
      )}
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
function ruleNames(i18n: I18n, rule: StatusRule, own: OwnPage | undefined) {
  return {
    source: calendarName(i18n, rule.source, own?.names),
    destination: calendarName(i18n, rule.destination, own?.names),
  }
}

function RuleName({ i18n, rule, own }: { i18n: I18n; rule: StatusRule; own: OwnPage | undefined }) {
  const names = ruleNames(i18n, rule, own)
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

/**
 * How many rules run, then a problem shared by several rules once, then every rule with its own
 * problems under it; a problem of no one rule comes first.
 */
function SyncBlock({ status, options, children }: { status: Status; options: Options; children: ReactNode }) {
  const i18n = useI18n()
  const { t } = i18n
  const { unattached, shared, byRule } = arrangeProblems(status)
  const named = new Map(status.rules.map((rule) => [rule.id, rule]))
  const stops = (group: SharedProblem) =>
    t("people.overview.stops", {
      rules: i18n.format.list(
        group.ruleIds.flatMap((id) => {
          const rule = named.get(id)
          return rule ? [t("overview.ruleName", ruleNames(i18n, rule, options.own))] : []
        }),
      ),
    })
  return (
    <Block title={t("people.overview.statusTitle")} className="user-overview-health">
      <div className="user-overview-verdict">
        <VerdictBadge verdict={status.status} />
        <p>{rulesRunning(i18n, status)}</p>
      </div>
      {(unattached.length > 0 || shared.length > 0 || status.rules.length > 0) && (
        <ul className="user-overview-list">
          {unattached.map((problem) => (
            <li key={`${problem.kind}:${problem.summary}`}>
              <ProblemDetail problem={problem} status={status} options={options} />
            </li>
          ))}
          {shared.map((group) => (
            <li key={`shared:${String(group.problem.cause)}`}>
              <ProblemDetail problem={group.problem} status={status} options={options} stops={stops(group)} />
            </li>
          ))}
          {status.rules.map((rule) => (
            <RuleItem key={rule.id} rule={rule} problems={byRule.get(rule.id) ?? []} status={status} options={options} />
          ))}
        </ul>
      )}
      {status.rules.length === 0 && <p className="user-overview-muted">{t("people.overview.noRules")}</p>}
      {children}
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
        <RuleName i18n={i18n} rule={rule} own={options.own} />
        <RuleStatusBadge state={rule.state} stopped={rule.problem?.kind === "stopped"} />
      </div>
      <p className="user-overview-muted">{lastSync(i18n, rule.last_succeeded_at, options.now)}</p>
      {problems.map((problem) => (
        <ProblemDetail key={`${problem.kind}:${problem.summary}`} problem={problem} status={status} options={options} />
      ))}
    </li>
  )
}

/** What the person keeps here and the calls their rules made, with one line on what the calls mean. */
function UseFacts({ resources }: { resources: ResourceUse }) {
  const i18n = useI18n()
  const { t } = i18n
  const facts = resourceFacts(i18n, resources)
  const since = i18n.format.shortDay(resources.since, true)
  const meaning = callsMeaning(i18n, resources.provider_calls)
  return (
    <div className="user-overview-use">
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
    </div>
  )
}
