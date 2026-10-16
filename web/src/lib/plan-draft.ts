import { ApiError, type PlanChange, type PlanLimits, type PlanSummary, type SyncInterval } from "@/lib/api"

/** One limit as the Plan editor holds it: the number typed, or No limit. */
export type LimitDraft = { amount: string; unlimited: boolean }

/** The counts a Plan limits, as the editor names its fields. */
export type LimitName = "rules" | "accounts" | "tokens"

/** A Plan as the editor holds it. It has no key: the server makes a new Plan's from its name. */
export type PlanDraft = Record<LimitName, LimitDraft> & { name: string; interval: SyncInterval }

/** A field of the Plan editor, so a refusal or a missing value can point at it. */
export type DraftField = "name" | LimitName | "interval"

export const LIMIT_NAMES: readonly LimitName[] = ["rules", "accounts", "tokens"]

/** The largest count a limit takes, as `COUNT_LIMIT` in domain/plans.py sets it. */
export const COUNT_LIMIT = 10_000

/** The least each count takes, as `PlanLimits` checks: a Plan may offer no Integration Tokens. */
export const LIMIT_MINIMUM: Readonly<Record<LimitName, number>> = { rules: 1, accounts: 1, tokens: 0 }

/** Where each count is in a saved Plan's limits. */
const SAVED: Readonly<Record<LimitName, Exclude<keyof PlanLimits, "sync_interval">>> = {
  rules: "rules",
  accounts: "connected_accounts",
  tokens: "integration_tokens",
}

function limitDraft(limit: number | null): LimitDraft {
  return limit === null ? { amount: "", unlimited: true } : { amount: String(limit), unlimited: false }
}

/** A new Plan starts with no limits and the first offered interval; an existing one as saved. */
export function draftOf(plan: PlanSummary | null, intervals: readonly SyncInterval[]): PlanDraft {
  if (plan === null) {
    const none = limitDraft(null)
    return { name: "", rules: none, accounts: none, tokens: none, interval: intervals[0] ?? "instant" }
  }
  const { limits } = plan
  return {
    name: plan.name,
    rules: limitDraft(limits.rules),
    accounts: limitDraft(limits.connected_accounts),
    tokens: limitDraft(limits.integration_tokens),
    interval: limits.sync_interval,
  }
}

/** null for No limit, the whole number typed while it is in range, or undefined when there is none. */
function limitValue(draft: PlanDraft, name: LimitName): number | null | undefined {
  const { amount, unlimited } = draft[name]
  if (unlimited) return null
  const value = Number(amount)
  const whole = amount.trim() !== "" && Number.isInteger(value)
  return whole && value >= LIMIT_MINIMUM[name] && value <= COUNT_LIMIT ? value : undefined
}

/** The first field Save waits for: an empty name, or a limit with no whole number in its range. */
export function missingField(draft: PlanDraft): "name" | LimitName | null {
  if (!draft.name.trim()) return "name"
  return LIMIT_NAMES.find((name) => limitValue(draft, name) === undefined) ?? null
}

/** What Save sends, or null while a field is missing. The server checks every value again. */
export function payloadOf(draft: PlanDraft): PlanChange | null {
  const rules = limitValue(draft, "rules")
  const accounts = limitValue(draft, "accounts")
  const tokens = limitValue(draft, "tokens")
  const name = draft.name.trim()
  if (!name || rules === undefined || accounts === undefined || tokens === undefined) return null
  return {
    name,
    limits: { rules, connected_accounts: accounts, integration_tokens: tokens, sync_interval: draft.interval },
  }
}

/** Whether a limit typed is lower than the Plan's saved one, so people it limits may have more. */
export function lowers(plan: PlanSummary | null, draft: PlanDraft, name: LimitName): boolean {
  if (plan === null || plan.limited_people === 0) return false
  const next = limitValue(draft, name)
  const saved = plan.limits[SAVED[name]]
  return typeof next === "number" && (saved === null || next < saved)
}

/**
 * The field a refusal of the Plan sent as `draft` names, or null when it names none, as when the
 * Plan was removed meanwhile. The server does not say which limit it refused, and No limit is
 * always allowed, so a limit refusal names the first limit with a number.
 */
export function refusedField(error: unknown, draft: PlanDraft): DraftField | null {
  if (!(error instanceof ApiError) || error.code !== "invalid_plan") return null
  const { reason } = error.params
  if (reason === "name" || reason === "interval") return reason
  if (reason === "limit") return LIMIT_NAMES.find((name) => !draft[name].unlimited) ?? null
  return null
}
