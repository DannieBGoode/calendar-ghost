import { providerName } from "@/i18n/api-errors"
import { incidentText } from "@/i18n/incident-text"
import type { I18n } from "@/i18n/translator"
import type { ResourceUse, ServerProblem, UserOverview, Verdict } from "@/lib/api"
import { causeOf, fixesItself, isAdministratorCause, type Cause } from "@/lib/causes"

/** Every Installation Status verdict, most urgent first, as CONTEXT.md lists them. */
export const VERDICTS: readonly Verdict[] = ["stalled", "stopped", "review", "waiting", "paused", "setup", "healthy"]

/** How a verdict's badge is colored: by whether, and how soon, someone needs to act. */
export type VerdictTone = "stopped" | "attention" | "neutral" | "healthy"

const TONES: Record<Verdict, VerdictTone> = {
  stalled: "stopped",
  stopped: "stopped",
  review: "attention",
  waiting: "attention",
  paused: "neutral",
  setup: "neutral",
  healthy: "healthy",
}

export function verdictTone(verdict: Verdict): VerdictTone {
  return TONES[verdict]
}

/**
 * A problem of the Operator Overview in the active language: from its Incident's message when
 * one explains it, otherwise by its kind. `blockedEvents` counts a blocked problem's events.
 */
export function problemText(i18n: I18n, problem: ServerProblem, blockedEvents: number): string {
  if (problem.message) return incidentText(i18n, problem)
  switch (problem.kind) {
    case "stalled":
    case "stopped":
    case "overdue":
      return i18n.t(`people.overview.problem.${problem.kind}`)
    case "blocked":
      return i18n.t("people.overview.problem.blocked", { count: blockedEvents })
    default:
      return problem.summary
  }
}

/** What a User keeps here, and each provider's calls their rules made, as short facts. */
export function resourceFacts(i18n: I18n, resources: ResourceUse): { kept: string[]; calls: string[] } {
  const { t } = i18n
  return {
    kept: [
      t("people.overview.kept.rules", { count: resources.rules }),
      t("people.overview.kept.accounts", { count: resources.connected_accounts }),
      t("people.overview.kept.activity", { count: resources.activity_entries }),
    ],
    calls: resources.provider_calls.map((calls) => {
      const total = t("people.overview.calls.total", { provider: providerName(i18n, calls.provider), count: calls.calls })
      const details = [
        t("people.overview.calls.rateLimited", { count: calls.rate_limited }),
        t("people.overview.calls.failed", { count: calls.failed }),
      ].join(", ")
      return t("people.overview.calls.list", { total, details })
    }),
  }
}

type StatusCalendar = UserOverview["status"]["rules"][number]["source"]

/**
 * A calendar as the Operator Overview names it: "Calendar 2" in the reader's language when it is
 * numbered in place of its name, otherwise its name. `ownNames` gives an administrator's own
 * calendars their names on their own page. A server too old to send numbers keeps its own label.
 */
export function calendarName(i18n: I18n, calendar: StatusCalendar, ownNames?: ReadonlyMap<number, string>): string {
  const number: unknown = calendar.number
  if (typeof number !== "number") return calendar.calendar
  return ownNames?.get(number) ?? i18n.t("people.overview.calendar", { number })
}

type OverviewStatus = UserOverview["status"]

/** How many of a person's rules run, which the status badge beside it does not say. */
export function rulesRunning(i18n: I18n, status: OverviewStatus): string {
  const { rules, running } = status.counts
  // Without rules, or with the scheduler stopped, the verdict's own sentence explains more.
  if (rules === 0 || status.status === "stalled") return i18n.t(`people.overview.verdict.${status.status}`)
  return i18n.t("people.overview.rulesRunning", { count: rules, running })
}

/** One problem said once for every rule it stops, such as one account's Lapsed Authorization. */
export type SharedProblem = { problem: ServerProblem; ruleIds: string[] }

export type ArrangedProblems = {
  /** Problems of no one rule, or of a rule no longer listed. */
  unattached: ServerProblem[]
  shared: SharedProblem[]
  byRule: ReadonlyMap<string, ServerProblem[]>
}

/**
 * A person's problems, placed where they are read: a lapsed account once, naming every rule it
 * stopped, instead of the same three lines under each; every other problem under its rule.
 */
export function arrangeProblems(status: OverviewStatus): ArrangedProblems {
  const listed = new Set(status.rules.map((rule) => rule.id))
  const unattached: ServerProblem[] = []
  const shared = new Map<string, SharedProblem>()
  const byRule = new Map<string, ServerProblem[]>()
  for (const problem of status.problems) {
    const ruleId = problem.rule_id
    if (!ruleId || !listed.has(ruleId)) {
      unattached.push(problem)
    } else if (problem.message?.code === "authorization_lapsed") {
      const key = String(problem.cause)
      const group = shared.get(key) ?? { problem, ruleIds: [] }
      group.ruleIds.push(ruleId)
      shared.set(key, group)
    } else {
      byRule.set(ruleId, [...(byRule.get(ruleId) ?? []), problem])
    }
  }
  return { unattached, shared: [...shared.values()], byRule }
}

type ProviderCalls = ResourceUse["provider_calls"][number]

/** A failure share above this reads as many: more than a few retried or not-found answers. */
const MANY_FAILED = 0.05

/** One line on whether a person's calls look normal, so a count such as "27 failed" means something. */
export function callsMeaning(i18n: I18n, calls: readonly ProviderCalls[]): string | null {
  const total = calls.reduce((sum, each) => sum + each.calls, 0)
  if (total === 0) return null
  const failed = calls.reduce((sum, each) => sum + each.failed, 0)
  const limited = calls.reduce((sum, each) => sum + each.rate_limited, 0)
  if (failed / total > MANY_FAILED) return i18n.t("people.overview.callsMeaning.manyFailed")
  return i18n.t(limited > 0 ? "people.overview.callsMeaning.limited" : "people.overview.callsMeaning.normal")
}

/**
 * Who reads a problem on a person's page: an administrator looking at someone else, by name, or
 * at their own page, where the steps are theirs.
 */
export type Audience = "administrator" | { name: string }

/** An administrator reading their own page, who also fixes the installation's own Causes. */
export const AS_ADMINISTRATOR: Audience = "administrator"

const REAUTHORIZE_KINDS = new Set(["authentication", "authorization"])

type Step = "reauthorize" | "preview" | "activity" | "overdue" | "waiting" | "stalled" | "administrator" | "calendar"

/** Whether a stopped problem is an account's Lapsed Authorization. */
function lapsed(problem: ServerProblem): boolean {
  const message = problem.message
  return (
    problem.kind === "stopped" &&
    (message?.code === "authorization_lapsed" || REAUTHORIZE_KINDS.has(String(message?.params.kind)))
  )
}

/** The step a problem's Cause gives, when its Cause decides it (ADR 0031). */
function causeStep(cause: Cause | null): Step | null {
  if (isAdministratorCause(cause)) return "administrator"
  if (fixesItself(cause)) return "waiting"
  if (cause === "access_revoked") return "reauthorize"
  if (cause === "calendar_forbidden" || cause === "calendar_not_found") return "calendar"
  return null
}

function step(problem: ServerProblem): Step {
  const byCause = causeStep(causeOf(problem))
  if (byCause !== null) return byCause
  switch (problem.kind) {
    case "stopped":
      return lapsed(problem) ? "reauthorize" : "preview"
    case "review":
    case "blocked":
      return "activity"
    default:
      return problem.kind
  }
}

/** The administrator's Cause: the reader's to fix, whoever's page it is on. */
function administratorStep(i18n: I18n, audience: Audience): string {
  return audience === "administrator"
    ? i18n.t("people.overview.next.administrator.administrator")
    : i18n.t("people.overview.next.administrator.person", { name: audience.name })
}

/**
 * The one next step for a problem, saying who takes it, in calendar language. An administrator
 * never acts on a User's own Cause: they read that the User fixes it from their dashboard.
 */
export function nextStep(i18n: I18n, problem: ServerProblem, audience: Audience): string {
  const next = step(problem)
  if (next === "waiting") return i18n.t("people.overview.next.waiting")
  if (next === "administrator") return administratorStep(i18n, audience)
  // Restarting Calendar Ghost is an administrator's, whoever's page it is on.
  if (next === "stalled") return i18n.t("people.overview.next.stalled")
  if (typeof audience === "object") return personStep(i18n, problem, audience.name)
  return i18n.t(`people.overview.next.${next}.self`)
}

/**
 * The next step, to an administrator looking at someone else: the person fixes their own problems
 * from their dashboard, so the administrator is offered nothing to do (ADR 0031).
 */
function personStep(i18n: I18n, problem: ServerProblem, name: string): string {
  if (causeOf(problem) === "unknown") return i18n.t("people.overview.next.ownCause.unknown", { name })
  return i18n.t("people.overview.next.ownCause.person", { name })
}

/** Where an administrator goes, on their own page, to take their own step. */
export type OwnTarget = "connections" | "rule"

/** The page of an administrator's own next step, when it has one; none for the installation's. */
export function ownStepTarget(problem: ServerProblem): OwnTarget | null {
  const next = step(problem)
  if (next === "reauthorize") return "connections"
  const onRule = next === "preview" || next === "overdue" || next === "calendar"
  return onRule && problem.rule_id ? "rule" : null
}

/** Steps a person takes themself, which the administrator can repeat to them if they ask. */
const SUPPORT_STEPS = ["reauthorize", "preview", "activity", "overdue", "calendar"] as const

/**
 * What a person does about their own problem, in the third person, for an administrator to repeat
 * if they ask for help; none for what only the administrator fixes, or what fixes itself.
 */
export function supportHint(i18n: I18n, problem: ServerProblem): string | null {
  const next = step(problem)
  const known = SUPPORT_STEPS.find((each) => each === next)
  return known ? i18n.t(`people.overview.ifTheyAsk.${known}`) : null
}
