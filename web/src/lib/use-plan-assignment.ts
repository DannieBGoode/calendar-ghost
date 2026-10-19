import { keepPreviousData, useQuery } from "@tanstack/react-query"

import { api } from "@/lib/api"
import { assignCandidates, movesTo } from "@/lib/plan-assignment"

/**
 * Who Assign people may give the Plan with key `plan` to, by email, narrowed by part of an email.
 * The last list stays while a new search is on its way. It is kept under People's key, so every
 * change to someone's Plan reads it again, but not while the Plan is being given (`giving`).
 */
export function usePlanCandidates(plan: string, search: string, giving: boolean) {
  return useQuery({
    queryKey: ["people", "plan-candidates", search],
    queryFn: () => api.planCandidates(search),
    placeholderData: keepPreviousData,
    select: (page) => assignCandidates(page, plan),
    enabled: !giving,
  })
}

/**
 * What giving the Plan to `userIds` would do, from a dry run that gives nothing: each person's
 * Plan now and what they would be over under it. `plan` is a Plan's key, or null for the Default
 * Plan, as Change plan offers it. Asked once for each list of people a Plan could limit while
 * Assign people or Change plan is open, never while a Plan is being given, and forgotten as it
 * closes, so it is asked afresh each time it opens.
 */
export function usePlanDryRun(plan: string | null, userIds: readonly string[], giving: boolean) {
  return useQuery({
    queryKey: ["plan-dry-run", plan, userIds],
    queryFn: () => api.assignPlans(movesTo(plan, userIds), true),
    enabled: userIds.length > 0 && !giving,
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: 0,
  })
}
