import { useQuery } from "@tanstack/react-query"

import { useI18n } from "@/i18n/provider"
import { api } from "@/lib/api"
import { planWarning } from "@/lib/plans"

/** The signed-in User's own Plan; a change to their rules, accounts, or tokens refreshes it. */
export const OWN_PLAN_QUERY = ["own-plan"] as const

/**
 * What the signed-in User's Plan allows and how much of it they have. Hints read it, so a failed
 * or pending read gives no hint and no warning: every control stays enabled, and the server
 * still checks each limit.
 */
export function useOwnPlan() {
  return useQuery({ queryKey: OWN_PLAN_QUERY, queryFn: api.ownPlan })
}

/** Whether a note should say that a change may keep a rule from starting again. */
export function usePlanWarning(): boolean {
  return planWarning(useOwnPlan().data)
}

/** Why Connect is unavailable: every calendar account place of the Plan is in use. */
export function useAccountLimitReason(): string | undefined {
  const { t } = useI18n()
  const plan = useOwnPlan().data
  const limit = plan?.limits?.connected_accounts
  if (plan?.may_connect_account !== false || typeof limit !== "number") return undefined
  return t("common.plan.accountLimit", { count: limit })
}

/** Why a new Integration Token cannot be issued: the Plan's tokens are all in use. */
export function useTokenLimitReason(): string | undefined {
  const { t } = useI18n()
  const plan = useOwnPlan().data
  const limit = plan?.limits?.integration_tokens
  if (plan?.may_issue_token !== false || typeof limit !== "number") return undefined
  return t("common.apiError.plan_limit_reached_integration_tokens", { count: limit })
}
