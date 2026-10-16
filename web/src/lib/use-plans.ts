import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import { api, type PeoplePage, type PlanChange, type PlanPayload, type PlanSummary, type PlansOverview } from "@/lib/api"
import { limitedPeople } from "@/lib/plans"
import { OWN_PLAN_QUERY } from "@/lib/use-own-plan"

/** Every Plan and the Plans setting; only Installation Administrators may read them. */
export const PLANS_QUERY = ["plans"] as const

/**
 * Every Plan and the Plans setting, read only while `enabled`: People's Plan filter asks for them
 * once its people show that a Plan exists, and Change plan as it opens.
 */
export function usePlanList(enabled = true) {
  return useQuery({ queryKey: PLANS_QUERY, queryFn: api.plans, enabled })
}

/**
 * The Plans People's Plan filter offers. They are read only once People's `page` shows that a Plan
 * exists, or the address names a `plan`, and kept once read, so the filter stays while a search
 * finds nobody. Undefined, and no filter, until then, or while no Plan exists and none is named.
 */
export function useFilterPlans(page: PeoplePage | undefined, plan: string): readonly PlanSummary[] | undefined {
  const planned = page?.users.some((person) => person.plan !== null) ?? false
  const plans = usePlanList(planned || plan !== "").data?.plans
  return plans && (plans.length > 0 || plan !== "") ? plans : undefined
}

/**
 * The first people who have a Plan, by email, and how many have it, for its Remove note. Kept
 * under People's key, so every change to someone's Plan reads them again.
 */
export function usePlanHolders(plan: string) {
  return useQuery({ queryKey: ["people", "plan-holders", plan], queryFn: () => api.planHolders(plan) })
}

/** The Plans setting's change: whether Plans limit people now, and the Default Plan. */
type SettingChange = { enabled: boolean; defaultPlan: string | null }

/**
 * What turning Plans on did: the Plan the server made the default when there was none, or how many
 * people Plans now limit.
 */
function turnedOnMessage({ t }: I18n, before: PlansOverview | undefined, after: PlansOverview): string {
  const made =
    before &&
    after.plans.find((plan) => plan.key === after.default_plan && !before.plans.some((known) => known.key === plan.key))
  if (made) return t("people.plans.saved.onNoLimits", { name: made.name })
  const count = limitedPeople(after.plans)
  return count > 0 ? t("people.plans.saved.on", { count }) : t("people.plans.saved.onNobody")
}

/** What a change of the Plans setting did, in the active language; empty when nothing to say. */
function settingMessage(i18n: I18n, before: PlansOverview | undefined, after: PlansOverview): string {
  const { t } = i18n
  if (before?.enabled !== after.enabled) {
    return after.enabled ? turnedOnMessage(i18n, before, after) : t("people.plans.saved.off")
  }
  const chosen = after.plans.find((plan) => plan.key === after.default_plan)
  return chosen ? t("people.plans.saved.defaultChanged", { name: chosen.name }) : ""
}

/**
 * Plans and the commands that change them, for Installation Administrators. Every change also
 * refreshes People, whose person pages show each person's Plan, and the administrator's own Plan.
 */
export function usePlans() {
  const i18n = useI18n()
  const { t } = i18n
  const queryClient = useQueryClient()
  const plans = usePlanList()
  const [message, setMessage] = useState("")
  const refreshOthers = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["people"] }),
      queryClient.invalidateQueries({ queryKey: OWN_PLAN_QUERY }),
    ])
  const saved = async (text: string) => {
    setMessage(text)
    await Promise.all([queryClient.invalidateQueries({ queryKey: PLANS_QUERY }), refreshOthers()])
  }
  const setting = useMutation({
    mutationFn: ({ enabled, defaultPlan }: SettingChange) => api.setPlansSetting(enabled, defaultPlan),
    onMutate: () => setMessage(""),
    onSuccess: async (overview) => {
      setMessage(settingMessage(i18n, queryClient.getQueryData<PlansOverview>(PLANS_QUERY), overview))
      queryClient.setQueryData(PLANS_QUERY, overview)
      await refreshOthers()
    },
  })
  const define = useMutation({
    mutationFn: (payload: PlanPayload) => api.definePlan(payload),
    onMutate: () => setMessage(""),
    onSuccess: (plan) => saved(t("people.plans.saved.defined", { name: plan.name })),
  })
  const change = useMutation({
    mutationFn: ({ key, payload }: { key: string; payload: PlanChange }) => api.changePlan(key, payload),
    onMutate: () => setMessage(""),
    onSuccess: (plan) => saved(t("people.plans.saved.changed", { name: plan.name })),
  })
  const remove = useMutation({
    mutationFn: (key: string) => api.removePlan(key),
    onMutate: () => setMessage(""),
    onSuccess: (_result, key) => {
      const listed = queryClient.getQueryData<PlansOverview>(PLANS_QUERY)?.plans.find((plan) => plan.key === key)
      return saved(t("people.plans.saved.removed", { name: listed?.name ?? key }))
    },
  })
  return { plans, setting, define, change, remove, message }
}

export type PlanCommands = ReturnType<typeof usePlans>
