import { ApiError } from "./api"

export type ActivityFailure = "session-expired" | "application-updated" | "service-error" | "unreachable"

export const activityFailureMessages: Record<ActivityFailure, string> = {
  "session-expired": "Your administrator session has expired. Sign in again to view operational activity.",
  "application-updated": "Calendar Sync was updated. Reload the page to continue.",
  "service-error": "The local service returned an error; try the request again.",
  unreachable:
    "The request did not reach the local service. It may have been restarting, or a browser extension such as a content blocker may be blocking it; try the request again.",
}

// A 404 from a known API path means this page predates the running service, so only a reload
// recovers; a failure without an HTTP response never reached the service at all.
export function activityFailure(errors: unknown[]): ActivityFailure {
  const statuses = errors.filter((error) => error instanceof ApiError).map((error) => error.status)
  if (statuses.includes(401)) return "session-expired"
  if (statuses.includes(404)) return "application-updated"
  if (statuses.length > 0) return "service-error"
  return "unreachable"
}

export function activityFailureRequiresReload(failure: ActivityFailure): boolean {
  return failure === "session-expired" || failure === "application-updated"
}
