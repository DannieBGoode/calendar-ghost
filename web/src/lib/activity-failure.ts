import type { MessageKey } from "@/i18n/types"

import { ApiError } from "./api"

export type ActivityFailure = "session-expired" | "application-updated" | "service-error" | "unreachable"

export const activityFailureMessages: Record<ActivityFailure, MessageKey> = {
  "session-expired": "activity.failure.message.sessionExpired",
  "application-updated": "activity.failure.message.applicationUpdated",
  "service-error": "activity.failure.message.serviceError",
  unreachable: "activity.failure.message.unreachable",
}

export const activityFailureActions: Record<ActivityFailure, MessageKey> = {
  "session-expired": "activity.failure.action.signIn",
  "application-updated": "activity.failure.action.reload",
  "service-error": "activity.failure.action.retry",
  unreachable: "activity.failure.action.retry",
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
