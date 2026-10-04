import type { Incident } from "@/lib/api"

import { messageParams } from "./api-errors"
import type { I18n } from "./translator"
import type { MessageKey } from "./types"

const FAILURE_SUMMARIES = {
  authentication: "common.incident.failure.authentication",
  authorization: "common.incident.failure.authorization",
  rate_limit: "common.incident.failure.rate_limit",
  temporary: "common.incident.failure.temporary",
  permanent: "common.incident.failure.permanent",
  infrastructure: "common.incident.failure.infrastructure",
} as const satisfies Record<string, MessageKey>

type IncidentMessage = NonNullable<Incident["message"]>

function isFailureKind(kind: unknown): kind is keyof typeof FAILURE_SUMMARIES {
  return typeof kind === "string" && Object.hasOwn(FAILURE_SUMMARIES, kind)
}

/** What failed at the provider, or null when the message names no failure this version knows. */
function failure(i18n: I18n, message: IncidentMessage): string | null {
  const kind = message.params.kind
  return isFailureKind(kind) ? i18n.t(FAILURE_SUMMARIES[kind], messageParams(i18n, message.params)) : null
}

function messageText(i18n: I18n, message: IncidentMessage): string | null {
  if (message.code === "provider_failure") return failure(i18n, message)
  if (message.code === "removal_stopped") {
    const reason = failure(i18n, message)
    return reason ? i18n.t("common.incident.removalStopped", { reason }) : null
  }
  const count = message.params.count
  if (message.code === "events_still_blocked" && typeof count === "number") {
    return i18n.t("common.incident.eventsStillBlocked", { count })
  }
  return null
}

/**
 * An Incident, or an Installation Status problem an Incident explains, in the active language.
 * One without a message this version knows keeps the server's English summary.
 */
export function incidentText(i18n: I18n, incident: Pick<Incident, "summary" | "message">): string {
  return (incident.message && messageText(i18n, incident.message)) ?? incident.summary
}
