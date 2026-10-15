import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import { api, type PlanChange, type PlanPayload, type PlansOverview } from "@/lib/api"
import { OWN_PLAN_QUERY } from "@/lib/use-own-plan"

/** Every Plan and the Plans setting; only Installation Administrators may read them. */
export const PLANS_QUERY = ["plans"] as const

/** The Plans setting's change: whether Plans limit people now, and the Default Plan. */
type SettingChange = { enabled: boolean; defaultPlan: string | null }

/** What a change of the Plans setting did, in the active language; empty when nothing to say. */
function settingMessage({ t }: I18n, before: PlansOverview | undefined, after: PlansOverview): string {
  if (before?.enabled !== after.enabled) return t(after.enabled ? "settings.plans.saved.on" : "settings.plans.saved.off")
  const chosen = after.plans.find((plan) => plan.key === after.default_plan)
  return chosen ? t("settings.plans.saved.defaultChanged", { name: chosen.name }) : ""
}

/**
 * Plans and the commands that change them, for Installation Administrators. Every change also
 * refreshes People, whose person pages show each person's Plan, and the administrator's own Plan.
 */
export function usePlans() {
  const i18n = useI18n()
  const { t } = i18n
  const queryClient = useQueryClient()
  const plans = useQuery({ queryKey: PLANS_QUERY, queryFn: api.plans })
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
    onSuccess: (plan) => saved(t("settings.plans.saved.defined", { name: plan.name })),
  })
  const change = useMutation({
    mutationFn: ({ key, payload }: { key: string; payload: PlanChange }) => api.changePlan(key, payload),
    onMutate: () => setMessage(""),
    onSuccess: (plan) => saved(t("settings.plans.saved.changed", { name: plan.name })),
  })
  const remove = useMutation({
    mutationFn: (key: string) => api.removePlan(key),
    onMutate: () => setMessage(""),
    onSuccess: (_result, key) => {
      const listed = queryClient.getQueryData<PlansOverview>(PLANS_QUERY)?.plans.find((plan) => plan.key === key)
      return saved(t("settings.plans.saved.removed", { name: listed?.name ?? key }))
    },
  })
  return { plans, setting, define, change, remove, message }
}

export type PlanCommands = ReturnType<typeof usePlans>
