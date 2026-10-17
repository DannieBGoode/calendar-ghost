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

/** Where each count is in a saved Plan's limits, and in how much the people it limits use. */
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

/**
 * A new Plan with another's limits, as Duplicate starts it, under `name`. A sync interval a later
 * release saved, which a new Plan may not be given, starts at the first offered one instead.
 */
export function copyDraft(plan: PlanSummary, name: string, intervals: readonly SyncInterval[]): PlanDraft {
  const copied = draftOf(plan, intervals)
  const interval = intervals.includes(copied.interval) ? copied.interval : (intervals[0] ?? "instant")
  return { ...copied, name, interval }
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

/**
 * How many of the people a Plan limits have more than a limit typed lower than its saved one, from
 * how much each of them uses: 0 when the limit is not lower, or nobody has more.
 */
export function peopleOver(plan: PlanSummary | null, draft: PlanDraft, name: LimitName): number {
  if (plan === null) return 0
  const next = limitValue(draft, name)
  const saved = plan.limits[SAVED[name]]
  if (typeof next !== "number" || (saved !== null && next >= saved)) return 0
  return plan.use[SAVED[name]].reduce((total, { in_use, people }) => (in_use > next ? total + people : total), 0)
}

/** What two Plan names that read as one have in common, as `_name_key` in domain/plans.py compares them. */
function nameKey(name: string): string {
  return name.normalize("NFKC").trim().toLowerCase()
}

/**
 * The refusal the server would answer for a name that another Plan, one of `others`, already reads
 * as, whatever its case or the spaces around it, so the editor says so before sending it; null
 * while the name is free. The server still checks, as two Plans can be saved at once.
 */
export function nameRefusal(draft: PlanDraft, others: readonly string[]): ApiError | null {
  const taken = others.find((other) => nameKey(other) === nameKey(draft.name))
  if (taken === undefined || !draft.name.trim()) return null
  return new ApiError("Another plan has this name.", 409, null, { code: "plan_name_taken", params: { name: taken } })
}

/**
 * The field a refusal of the Plan sent as `draft` names, or null when it names none, as when the
 * Plan was removed meanwhile. The server does not say which limit it refused, and No limit is
 * always allowed, so a limit refusal names the first limit with a number.
 */
export function refusedField(error: unknown, draft: PlanDraft): DraftField | null {
  if (!(error instanceof ApiError)) return null
  if (error.code === "plan_name_taken") return "name"
  if (error.code !== "invalid_plan") return null
  const { reason } = error.params
  if (reason === "name" || reason === "interval") return reason
  if (reason === "limit") return LIMIT_NAMES.find((name) => !draft[name].unlimited) ?? null
  return null
}
