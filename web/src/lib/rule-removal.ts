import { useMutationState } from "@tanstack/react-query"

import { ApiError, type ProjectionHandling } from "@/lib/api"
import { plural } from "@/lib/rule-change"

/**
 * Rule details refresh this often while a removal runs. The service commits each deleted
 * projection, so the rule's mapping count falls as the removal progresses.
 */
export const REMOVAL_REFRESH_MS = 2_000

export type RemovalRequest = { handling: ProjectionHandling; total: number }
export type ActiveRemoval = RemovalRequest & { startedAt: number }

const REMOVAL_KEY = "rule-removal"

export function removalMutationKey(ruleId: string) {
  return [REMOVAL_KEY, ruleId] as const
}

/** The running removal for a rule. It lives in the mutation cache, so it survives navigation. */
export function useActiveRemoval(ruleId: string): ActiveRemoval | undefined {
  const [active] = useMutationState({
    filters: { mutationKey: removalMutationKey(ruleId), status: "pending" },
    select: (mutation) => ({
      ...(mutation.state.variables as RemovalRequest),
      startedAt: mutation.state.submittedAt,
    }),
  })
  return active
}

/** Rules with a removal running in this browser session, for list badges. */
export function useRemovingRuleIds(): ReadonlySet<string> {
  const ids = useMutationState({
    filters: { mutationKey: [REMOVAL_KEY], status: "pending" },
    select: (mutation) => String(mutation.options.mutationKey?.[1]),
  })
  return new Set(ids)
}

export function removalProgress(
  request: RemovalRequest,
  remaining: number,
  destination: string,
): { done: number | null; label: string } {
  if (request.total === 0) return { done: null, label: "Removing the rule…" }
  if (request.handling === "detach") {
    return {
      done: null,
      label: `Keeping ${plural(request.total, "event")} in ${destination} as ordinary events…`,
    }
  }
  const done = Math.min(request.total, Math.max(0, request.total - remaining))
  // Conflicted events leave the count too, but stay in Google, so this is not a deletion count.
  return { done, label: `Handled ${done} of ${plural(request.total, "projection")} in ${destination}` }
}

export function elapsedLabel(milliseconds: number): string {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000))
  if (seconds < 60) return `${seconds} s`
  return `${Math.floor(seconds / 60)} min ${seconds % 60} s`
}

/**
 * A dropped connection or gateway timeout says nothing about the removal itself: the service
 * keeps working after the browser stops waiting. The service itself never answers 502 or 504, so
 * those come from a proxy in front of it.
 */
export function removalConnectionLost(error: unknown): boolean {
  return !(error instanceof ApiError) || error.status === 502 || error.status === 504
}

export function removalErrorMessage(error: Error): string {
  return removalConnectionLost(error)
    ? "The connection closed before the removal finished. It may still be running, so wait a minute, then check this page before retrying."
    : error.message
}
