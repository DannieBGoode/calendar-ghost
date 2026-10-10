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
 * numbered in place of its name, otherwise its name. `ownNames` adds the person's own name for each
 * number, for the person themself only. A server too old to send numbers keeps its own label.
 */
export function calendarName(i18n: I18n, calendar: StatusCalendar, ownNames?: ReadonlyMap<number, string>): string {
  const number: unknown = calendar.number
  if (typeof number !== "number") return calendar.calendar
  const own = ownNames?.get(number)
  return own === undefined
    ? i18n.t("people.overview.calendar", { number })
    : i18n.t("people.overview.calendarNamed", { number, name: own })
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
 * Who reads a problem: the person themself, the person themself when they administer the
 * installation, or an administrator looking at someone else, by name.
 */
export type Audience = "self" | "administrator" | { name: string }

/** The person themself, reading what administrators see about them. */
export const THEMSELF: Audience = "self"

/** The person themself, who also administers the installation and so fixes its Causes. */
export const AS_ADMINISTRATOR: Audience = "administrator"

/** The signed-in User's own overview; every change to their rules, accounts, or Activity refreshes it. */
export const OWN_OVERVIEW_QUERY = ["own-overview"] as const

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

/** The administrator's Cause, to whoever reads it: theirs to fix, or not the User's. */
function administratorStep(i18n: I18n, problem: ServerProblem, audience: Audience): string {
  if (audience === "administrator") return i18n.t("people.overview.next.administrator.administrator")
  if (audience !== "self") return i18n.t("people.overview.next.administrator.person", { name: audience.name })
  return lapsed(problem)
    ? i18n.t("people.overview.next.administrator.selfLapsed")
    : i18n.t("people.overview.next.administrator.self")
}

/**
 * The one next step for a problem, saying who takes it, in calendar language. An administrator
 * never acts on a User's own Cause: they read that the User fixes it from their dashboard.
 */
export function nextStep(i18n: I18n, problem: ServerProblem, audience: Audience): string {
  const next = step(problem)
  if (next === "waiting") return i18n.t("people.overview.next.waiting")
  if (next === "administrator") return administratorStep(i18n, problem, audience)
  if (typeof audience === "object") return personStep(i18n, problem, next, audience.name)
  return i18n.t(`people.overview.next.${next}.self`)
}

/**
 * The next step, to an administrator looking at someone else. A stalled scheduler is theirs to
 * restart; every other problem the person fixes from their own dashboard, so the administrator is
 * offered nothing to do (ADR 0031).
 */
function personStep(i18n: I18n, problem: ServerProblem, next: Step, name: string): string {
  if (next === "stalled") return i18n.t("people.overview.next.stalled.person")
  if (causeOf(problem) === "unknown") return i18n.t("people.overview.next.ownCause.unknown", { name })
  return i18n.t("people.overview.next.ownCause.person", { name })
}

/** Where the person themself goes for a problem's next step, when it is a page of their own. */
export function ownStepTarget(problem: ServerProblem, audience: Audience = THEMSELF): OwnTarget | null {
  const next = step(problem)
  // Once an administrator fixes their Cause, Check access restarts what the lapse stopped.
  if (next === "administrator") return audience === "self" && lapsed(problem) ? "connections" : null
  return problem.rule_id || !RULE_STEPS.has(next) ? (STEP_TARGETS[next] ?? null) : null
}

type OwnTarget = "connections" | "rule" | "activity"

const STEP_TARGETS: Partial<Record<Step, OwnTarget>> = {
  reauthorize: "connections",
  preview: "rule",
  overdue: "rule",
  calendar: "rule",
  activity: "activity",
}

/** Steps taken on the problem's own rule, so only a problem naming one has them. */
const RULE_STEPS: ReadonlySet<Step> = new Set(["preview", "overdue", "calendar"])
