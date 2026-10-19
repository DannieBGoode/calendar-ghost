import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api, type PeoplePage, type PeopleQuery, type PlanChange, type PlanPayload, type PlanSummary } from "@/lib/api"
import type { PlanMoves } from "@/lib/plan-assignment"
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
 * The Plans People's Plan and Limits filters offer. They are read only once People's `page` shows
 * that a Plan exists, or the address names a `plan` or people `over` a limit, and kept once read,
 * so the filters stay while a search finds nobody. Undefined, and no filters, until then, or while
 * no Plan exists and none is named.
 */
export function useFilterPlans(
  page: PeoplePage | undefined,
  { plan, over }: Pick<PeopleQuery, "plan" | "over">,
): readonly PlanSummary[] | undefined {
  const planned = page?.users.some((person) => person.plan !== null) ?? false
  const plans = usePlanList(planned || plan !== "" || over).data?.plans
  return plans && (plans.length > 0 || plan !== "") ? plans : undefined
}

/**
 * The first people who have a Plan, by email, and how many have it, for why Remove waits. Read
 * only while `enabled`, as once its row menu opens, and kept under People's key, so every change
 * to someone's Plan reads them again.
 */
export function usePlanHolders(plan: string, enabled = true) {
  return useQuery({ queryKey: ["people", "plan-holders", plan], queryFn: () => api.planHolders(plan), enabled })
}

/**
 * Who has a Plan, by email, as its panel lists them, kept under People's key, so every change to
 * someone's Plan reads them again.
 */
export function usePlanPeople(plan: string) {
  return useQuery({ queryKey: ["people", "plan-people", plan], queryFn: () => api.planPeople(plan) })
}

/**
 * The Plans setting's change: whether Plans limit people now, and the Default Plan; `undo` when a
 * toast's Undo asks for it, whose refusal shows in a toast, where Undo was pressed.
 */
export type SettingChange = { enabled: boolean; defaultPlan: string | null; undo?: boolean }

/**
 * Giving Plans to people from one Plan's panel, `from`, its key, `via` Assign people (`give`),
 * Change plan for someone who has it (`change`), or Undo, which gives each person back the Plan they
 * had; a refusal shows where the command came from. One call gives every move, all or none.
 */
export type AssignCommand = { from: string; via: "give" | "change" | "undo"; moves: PlanMoves }

/**
 * Plans and the commands that change them, for Installation Administrators. Every change lists
 * the Plans again and refreshes People, whose person pages show each person's Plan, and the
 * administrator's own Plan. What a change did is for its caller to say.
 */
export function usePlans() {
  const queryClient = useQueryClient()
  const plans = usePlanList()
  const refreshOthers = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["people"] }),
      queryClient.invalidateQueries({ queryKey: OWN_PLAN_QUERY }),
    ])
  const saved = () => Promise.all([queryClient.invalidateQueries({ queryKey: PLANS_QUERY }), refreshOthers()])
  const setting = useMutation({
    mutationFn: ({ enabled, defaultPlan }: SettingChange) => api.setPlansSetting(enabled, defaultPlan),
    onSuccess: async (overview) => {
      queryClient.setQueryData(PLANS_QUERY, overview)
      await refreshOthers()
    },
  })
  const define = useMutation({ mutationFn: (payload: PlanPayload) => api.definePlan(payload), onSuccess: saved })
  const change = useMutation({
    mutationFn: ({ key, payload }: { key: string; payload: PlanChange }) => api.changePlan(key, payload),
    onSuccess: saved,
  })
  // A refused removal reads the Plans again too: the refusal usually means someone has it now.
  const remove = useMutation({ mutationFn: (key: string) => api.removePlan(key), onSuccess: saved, onError: saved })
  const assign = useMutation({ mutationFn: ({ moves }: AssignCommand) => api.assignPlans(moves, false), onSuccess: saved })
  return { plans, setting, define, change, remove, assign }
}

export type PlanCommands = ReturnType<typeof usePlans>
