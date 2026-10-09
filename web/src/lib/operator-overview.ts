import { providerName } from "@/i18n/api-errors"
import { incidentText } from "@/i18n/incident-text"
import type { I18n } from "@/i18n/translator"
import type { ResourceUse, ServerProblem, UserOverview, Verdict } from "@/lib/api"

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

/** A calendar as the Operator Overview names it: "Calendar 2" in the reader's language when it is
 * numbered in place of its name, otherwise its name. */
export function calendarName(i18n: I18n, calendar: StatusCalendar): string {
  return calendar.number === null ? calendar.calendar : i18n.t("people.overview.calendar", { number: calendar.number })
}

/** Who acts on a problem: the person themself in their own Settings, or someone an administrator
 * is looking at, by name. */
export type Audience = "self" | { name: string }

/** The person themself, reading what administrators see about them. */
export const THEMSELF: Audience = "self"

const REAUTHORIZE_KINDS = new Set(["authentication", "authorization"])

function step(problem: ServerProblem): "reauthorize" | "preview" | "activity" | "overdue" | "waiting" | "stalled" {
  switch (problem.kind) {
    case "stopped": {
      const message = problem.message
      const lapsed =
        message?.code === "authorization_lapsed" || REAUTHORIZE_KINDS.has(String(message?.params.kind))
      return lapsed ? "reauthorize" : "preview"
    }
    case "review":
    case "blocked":
      return "activity"
    default:
      return problem.kind
  }
}

/** The one next step for a problem, saying who takes it, in calendar language. */
export function nextStep(i18n: I18n, problem: ServerProblem, audience: Audience): string {
  const next = step(problem)
  if (next === "waiting") return i18n.t("people.overview.next.waiting")
  return audience === "self"
    ? i18n.t(`people.overview.next.${next}.self`)
    : i18n.t(`people.overview.next.${next}.person`, { name: audience.name })
}
