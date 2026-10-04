import type { Incident } from "@/lib/api"

import type { I18n } from "./translator"

/** An Incident's text for the administrator. */
export function incidentText(_i18n: I18n, incident: Pick<Incident, "summary">): string {
  // The server sends English summaries until Incident messages exist.
  return incident.summary
}
