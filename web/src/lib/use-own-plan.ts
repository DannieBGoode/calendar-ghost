import { useQuery } from "@tanstack/react-query"

import { useI18n } from "@/i18n/provider"
import { api, type OwnPlan, type RuleSummary } from "@/lib/api"
import { previewedStartRefusal } from "@/lib/plans"

/** The signed-in User's own Plan; a change to their rules, accounts, or tokens refreshes it. */
export const OWN_PLAN_QUERY = ["own-plan"] as const

/** What the signed-in User's Plan allows and how much of it they have, for Your plan. */
export function useOwnPlan() {
  return useQuery({ queryKey: OWN_PLAN_QUERY, queryFn: api.ownPlan })
}

/**
 * The Plan every hint and warning reads. A pending or failed read gives none: every control stays
 * enabled, and the server still checks each limit. A failed refresh keeps the earlier answer in
 * the cache, so it is dropped here too: an account deleted or a token revoked since may have
 * freed a place.
 */
function usePlanHints(): OwnPlan | undefined {
  const { data, isError } = useOwnPlan()
  return isError ? undefined : data
}

/**
 * Whether a note should say that a privacy edit, a Pause, or a Disconnect may keep a rule from
 * starting again: only Rule Replacement keeps a rule's place under the rule limit, and the User
 * has excess counted rules or held rules waiting to resume (ADR 0038, ADR 0039).
 */
export function usePlanWarning(): boolean {
  const plan = usePlanHints()
  return plan?.over_rule_limit === true || (plan?.held_rules ?? 0) > 0
}

/**
 * Why Start would refuse each previewed rule a page shows, from Your plan; null for a rule that
 * may start, and for every rule while the Plan is unknown.
 */
export function usePreviewedStartRefusal(): (rule: Pick<RuleSummary, "state" | "keeps_place">) => string | null {
  const i18n = useI18n()
  const plan = usePlanHints()
  return (rule) => previewedStartRefusal(i18n, plan, rule)
}

/** Why Connect is unavailable: every calendar account place of the Plan is in use. */
export function useAccountLimitReason(): string | undefined {
  const { t } = useI18n()
  const plan = usePlanHints()
  const limit = plan?.limits?.connected_accounts
  if (plan?.may_connect_account !== false || typeof limit !== "number") return undefined
  return t("common.plan.accountLimit", { count: limit })
}

/**
 * Why a new Integration Token cannot be issued: the Plan includes none, or its tokens are all in
 * use. It reads as the server's refusal does.
 */
export function useTokenLimitReason(): string | undefined {
  const { t } = useI18n()
  const plan = usePlanHints()
  const limit = plan?.limits?.integration_tokens
  if (plan?.may_issue_token !== false || typeof limit !== "number") return undefined
  return limit === 0
    ? t("common.apiError.plan_limit_reached_integration_tokens_none")
    : t("common.apiError.plan_limit_reached_integration_tokens", { count: limit })
}

/**
 * How many rules the Plan lets sync at once, for a note beside Create sync rule, so the limit is
 * known before a rule is built and previewed. None while nothing limits rules or the Plan is unknown.
 */
export function useRuleLimitNote(): string | undefined {
  const { t } = useI18n()
  const limit = usePlanHints()?.limits?.rules
  return typeof limit === "number" ? t("rules.list.planLimit", { count: limit }) : undefined
}

/** The keep chooser only applies to a confirmed finite Plan; unknown reads link to Your plan Retry. */
export function usePlanHoldStep(): "choose" | "retry" | null {
  const plan = usePlanHints()
  if (!plan?.basis) return "retry"
  return plan.basis === "plan" && typeof plan.limits?.rules === "number" ? "choose" : null
}
