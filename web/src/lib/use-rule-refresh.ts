import { useQueryClient } from "@tanstack/react-query"

import { RULE_CHANGE_QUERIES } from "@/lib/use-rule-commands"

/** Refreshes a rule that changed in place, and every view a rule change affects. */
export function useRuleInvalidation(ruleId: string) {
  const queryClient = useQueryClient()
  return async () => {
    await Promise.all(
      [...RULE_CHANGE_QUERIES, ["rule", ruleId]].map((queryKey) => queryClient.invalidateQueries({ queryKey })),
    )
  }
}

/** Forgets a rule that no longer exists and refreshes every view a rule change affects. */
export function useRuleExit(ruleId: string) {
  const queryClient = useQueryClient()
  return async () => {
    queryClient.removeQueries({ queryKey: ["rule", ruleId] })
    await Promise.all(
      RULE_CHANGE_QUERIES.map((queryKey) => queryClient.invalidateQueries({ queryKey })),
    )
  }
}
