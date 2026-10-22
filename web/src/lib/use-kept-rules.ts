import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { api } from "@/lib/api"
import { OWN_PLAN_QUERY, useOwnPlan } from "@/lib/use-own-plan"

/** A keep choice can swap holds, changing every surface that reports the User's rule status. */
const CHOICE_QUERIES = [OWN_PLAN_QUERY, ["rules"], ["rule"], ["dashboard"], ["people"], ["installation-health"]] as const

/** The complete keep choice and its refresh have separate outcomes: a failed read cannot undo a save. */
export function useKeptRules() {
  const client = useQueryClient()
  const plan = useOwnPlan()
  const names = useQuery({ queryKey: ["rules"], queryFn: api.rules })
  const [refreshFailed, setRefreshFailed] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  async function refresh() {
    setRefreshing(true)
    try {
      const results = await Promise.allSettled(
        CHOICE_QUERIES.map((queryKey) => client.invalidateQueries({ queryKey }, { throwOnError: true })),
      )
      setRefreshFailed(results.some((result) => result.status === "rejected"))
    } finally {
      setRefreshing(false)
    }
  }
  const save = useMutation({ mutationFn: (ruleIds: string[]) => api.chooseKeptRules(ruleIds), retry: false, onSuccess: refresh })
  return { plan, names, save, refresh, refreshFailed, pending: save.isPending || refreshing }
}
