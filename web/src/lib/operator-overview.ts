import { providerName } from "@/i18n/api-errors"
import { incidentText } from "@/i18n/incident-text"
import type { I18n } from "@/i18n/translator"
import type { ResourceUse, ServerProblem, Verdict } from "@/lib/api"

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
