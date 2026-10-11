import type { I18n } from "@/i18n/translator"
import type { MessageKey } from "@/i18n/types"
import type { CalendarProvider, Incident } from "@/lib/api"
import { causeOf, howToFixUrl, isAdministratorCause, type Cause } from "@/lib/causes"
import { providerOf, providerWords } from "@/lib/providers"

/** What the administrator can do to fix an open incident, if anything. */
type IncidentAction =
  | { kind: "settings"; label: string; accountId: string | null }
  | { kind: "rule"; ruleId: string; label: string }
  | { kind: "blocked"; ruleId: string; label: string }

/** Where a resolved incident leads: its rule's history, to see the runs around it. */
type IncidentFollowUp = { kind: "history"; ruleId: string; label: string }

/** The one next step an incident's details offer: its fix while open, its follow-up once resolved. */
export type IncidentStep = IncidentAction | IncidentFollowUp

/** The server's one next step for an incident (ADR 0033); the Web UI only words it. */
type ServerStep = NonNullable<Incident["step"]>

/** What each step says while the incident is open, and the button that takes it. */
const STEPS: Record<ServerStep, { detail: MessageKey | null; label: MessageKey | null }> = {
  reauthorize: { detail: "activity.incidents.guidance.authorization", label: "activity.incidents.action.reauthorize" },
  recover_rule: { detail: "activity.incidents.guidance.accessRenewed", label: "activity.incidents.action.recover" },
  review_rule: { detail: "activity.incidents.guidance.stopped", label: "activity.incidents.action.review" },
  see_blocked: { detail: "activity.incidents.guidance.conflict", label: "activity.incidents.action.seeBlocked" },
  wait: { detail: "activity.incidents.guidance.retrying", label: null },
  administrator: { detail: "activity.incidents.guidance.administrator", label: null },
  see_history: { detail: null, label: "activity.incidents.action.seeActivity" },
}

/** The button for the incident's step; the server offers a rule's steps only while it exists. */
function stepAction(incident: Incident, step: ServerStep, label: string): IncidentStep | null {
  if (step === "reauthorize") return { kind: "settings", label, accountId: incident.account_id }
  const ruleId = incident.rule_id
  if (!ruleId) return null
  switch (step) {
    case "recover_rule":
    case "review_rule":
      return { kind: "rule", ruleId, label }
    case "see_blocked":
      return { kind: "blocked", ruleId, label }
    case "see_history":
      return { kind: "history", ruleId, label }
    default:
      return null
  }
}

const RESOLUTIONS: Record<NonNullable<Incident["resolution"]>, MessageKey> = {
  sync_succeeded: "activity.incidents.resolution.syncSucceeded",
  blocks_cleared: "activity.incidents.resolution.blocksCleared",
  rule_removed: "activity.incidents.resolution.ruleRemoved",
  access_restored: "activity.incidents.resolution.accessRestored",
}

/** Why a resolved incident closed; null when it closed before the reason was recorded. */
export function incidentResolution(i18n: I18n, incident: Incident): string | null {
  return incident.resolution ? i18n.t(RESOLUTIONS[incident.resolution], providerWords(i18n, incident.provider)) : null
}

/** When a resolved incident closed; older ones only know when they were last updated. */
export function incidentClosedAt(incident: Incident): string {
  return incident.resolved_at ?? incident.updated_at
}

/** How many incidents still need attention; Activity's Incidents tab counts them. */
export function openIncidentCount(incidents: Incident[]): number {
  return incidents.filter((incident) => incident.state === "open").length
}

export type IncidentDuration = { unit: "moment" | "minute" | "hour" | "day"; count: number }

const MINUTE = 60_000

/** How long a resolved incident stayed open, to the nearest unit; null while it is open. */
export function incidentDuration(incident: Incident): IncidentDuration | null {
  if (incident.state === "open") return null
  const minutes = Math.floor((Date.parse(incidentClosedAt(incident)) - Date.parse(incident.opened_at)) / MINUTE)
  if (Number.isNaN(minutes)) return null
  if (minutes < 1) return { unit: "moment", count: 0 }
  if (minutes < 60) return { unit: "minute", count: minutes }
  const hours = Math.round(minutes / 60)
  if (hours < 24) return { unit: "hour", count: hours }
  return { unit: "day", count: Math.round(hours / 24) }
}

/** What an incident's details show, beyond its row. */
export type IncidentDetail = {
  /** What an open incident means, or how a resolved one closed. */
  explanation: string | null
  cause: Cause | null
  step: IncidentStep | null
  /** The troubleshooting section for an open incident the administrator must fix. */
  fixUrl: string | null
}

/**
 * Who reads the incident: only an administrator learns an administrator's Cause (ADR 0031). The
 * providers this installation configured say where each one's troubleshooting guide helps.
 */
export type IncidentReader = { administrator: boolean; providers: readonly CalendarProvider[] }

export function incidentDetail(i18n: I18n, incident: Incident, reader: IncidentReader): IncidentDetail {
  if (incident.step === "administrator" && !reader.administrator) return unavailableDetail(i18n, incident)
  const cause = shownCause(incident, reader)
  const open = incident.state === "open"
  return {
    explanation: open ? stepDetail(i18n, incident) : incidentResolution(i18n, incident),
    cause,
    step: incidentAction(i18n, incident),
    fixUrl: open ? howToFixUrl(cause, providerOf(reader.providers, incident.provider)) : null,
  }
}

/** The Cause the reader may read: none unrecognised, and an administrator's only to them. */
function shownCause(incident: Incident, reader: IncidentReader): Cause | null {
  const cause = causeOf(incident)
  if (cause === "unknown") return null
  return isAdministratorCause(cause) && !reader.administrator ? null : cause
}

function stepDetail(i18n: I18n, incident: Incident): string | null {
  const detail = incident.step ? STEPS[incident.step].detail : null
  return detail ? i18n.t(detail, providerWords(i18n, incident.provider)) : null
}

function incidentAction(i18n: I18n, incident: Incident): IncidentStep | null {
  const label = incident.step ? STEPS[incident.step].label : null
  return incident.step && label ? stepAction(incident, incident.step, i18n.t(label)) : null
}

/**
 * An administrator's Cause, as anyone else reads it: their calendar is not available right now,
 * with Check access to try again, never which Cause or that an administrator fixes it (ADR 0031).
 */
function unavailableDetail(i18n: I18n, incident: Incident): IncidentDetail {
  const label = i18n.t("activity.incidents.action.checkAccess")
  return {
    explanation: i18n.t("activity.incidents.guidance.unavailable", providerWords(i18n, incident.provider)),
    cause: null,
    step: { kind: "settings", label, accountId: incident.account_id },
    fixUrl: null,
  }
}
