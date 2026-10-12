import { HowToFixLink } from "@/components/how-to-fix-link"
import { useI18n } from "@/i18n/provider"
import type { ServerProblem, UserOverview } from "@/lib/api"
import { causeAddsToProblem, causeOf, causeText, howToFixUrl, isAdministratorCause, retryTiming } from "@/lib/causes"
import { nextStep, ownStepTarget, problemText, supportHint, type Audience } from "@/lib/operator-overview"
import { providerOf } from "@/lib/providers"
import { useProviders } from "@/lib/use-providers"

type Status = UserOverview["status"]

/** An administrator's own page: their calendars by name, and the way to their own steps. */
export type OwnPage = {
  names: ReadonlyMap<number, string>
  openRule: (ruleId: string) => void
  openConnections: () => void
}

export type ProblemOptions = {
  now: number
  audience: Audience
  own?: OwnPage | undefined
}

/**
 * What went wrong, its likely cause when that adds something, who takes the next step and how,
 * and since when. `stops` names the rules one problem stopped, when it is said once for them all.
 */
export function ProblemDetail({
  problem,
  status,
  options,
  stops,
}: {
  problem: ServerProblem
  status: Status
  options: ProblemOptions
  stops?: string
}) {
  const i18n = useI18n()
  const cause = causeOf(problem)
  const timing = retryTiming(i18n, problem, status.scheduler.next_pass_at ?? null, options.now)
  return (
    <div className="user-overview-problem" data-owner={cause ? (isAdministratorCause(cause) ? "administrator" : "user") : undefined}>
      <p className="user-overview-problem-text">{problemText(i18n, problem, status.counts.blocked_events)}</p>
      {stops && <p className="user-overview-muted">{stops}</p>}
      {causeAddsToProblem(cause) && <p className="user-overview-muted">{causeText(i18n, cause, problem.provider)}</p>}
      <ProblemStep problem={problem} options={options} />
      {typeof options.audience === "object" && <SupportHint problem={problem} />}
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
function ProblemStep({ problem, options }: { problem: ServerProblem; options: ProblemOptions }) {
  const i18n = useI18n()
  const providers = useProviders()
  const fix = howToFixUrl(causeOf(problem), providerOf(providers, problem.provider))
  return (
    <p className="user-overview-next">
      {nextStep(i18n, problem, options.audience)}
      {fix && (
        <>
          {" "}
          <HowToFixLink href={fix} />
        </>
      )}
      {options.own && <OwnStep problem={problem} own={options.own} />}
    </p>
  )
}

/** On an administrator's own page, the way to their own step: their connections or the rule. */
function OwnStep({ problem, own }: { problem: ServerProblem; own: OwnPage }) {
  const { t } = useI18n()
  const target = ownStepTarget(problem)
  const rule = problem.rule_id
  if (target === null || (target === "rule" && !rule)) return null
  const open = target === "connections" ? own.openConnections : () => rule && own.openRule(rule)
  return (
    <>
      {" "}
      <button type="button" className="text-link inline-link" onClick={open}>
        {t(`people.overview.go.${target}`)}
      </button>
    </>
  )
}

/** Quietly, what the person does about their own problem, should they ask the administrator. */
function SupportHint({ problem }: { problem: ServerProblem }) {
  const i18n = useI18n()
  const hint = supportHint(i18n, problem)
  return hint ? <p className="user-overview-muted">{hint}</p> : null
}
