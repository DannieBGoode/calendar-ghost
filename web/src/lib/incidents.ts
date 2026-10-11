import type { I18n } from "@/i18n/translator"
import type { MessageKey } from "@/i18n/types"
import type { ConnectedAccount, Incident } from "@/lib/api"
import { causeOf, howToFixUrl, type Cause } from "@/lib/causes"

/** What the administrator can do about an incident, if anything: fix an open one, or review a resolved one. */
export type IncidentAction =
  | { kind: "settings"; label: string; accountId: string | null }
  | { kind: "rule"; ruleId: string; label: string }
  | { kind: "blocked"; ruleId: string; label: string }
  | { kind: "history"; ruleId: string; label: string }

export type IncidentGuidance = { detail: string | null; action: IncidentAction | null }

/** What an incident's rule looks like now; null when the incident has no rule or it is gone. */
export type IncidentRuleState = { accessRenewed: boolean }

/**
 * Whether the rule's Google access was renewed after the incident last recorded a failure. An
 * authorization failure leaves its account connected, so being connected proves nothing; only
 * reauthorizing the account that failed does, with every account of the rule connected. When
 * the failing account was not recorded, every account of the rule must have been reauthorized.
 */
export function accessRenewedSince(incident: Incident, accounts: (ConnectedAccount | undefined)[]): boolean {
  const lastFailure = Date.parse(incident.updated_at)
  const renewed = (account: ConnectedAccount | undefined) =>
    account?.authorized_at != null && Date.parse(account.authorized_at) > lastFailure
  if (accounts.some((account) => account?.state !== "connected")) return false
  if (incident.account_id === null) return accounts.every(renewed)
  return renewed(accounts.find((account) => account?.id === incident.account_id))
}

const AUTHORIZATION = new Set(["authentication", "authorization"])
const STOPPED = new Set(["permanent", "infrastructure"])
const RETRYING = new Set(["rate_limit", "temporary"])

/** An action on the incident's rule, offered only while the rule still exists. */
function ruleAction(kind: "rule" | "blocked", ruleId: string | null, label: string): IncidentAction | null {
  return ruleId ? { kind, ruleId, label } : null
}

function authorizationGuidance(
  i18n: I18n,
  incident: Incident,
  ruleId: string | null,
  rule: IncidentRuleState | null,
): IncidentGuidance {
  // Reauthorizing renews access but leaves the rule stopped; only its recovery closes this.
  if (ruleId && rule?.accessRenewed) {
    return {
      detail: i18n.t("activity.incidents.guidance.accessRenewed"),
      action: { kind: "rule", ruleId, label: i18n.t("activity.incidents.action.recover") },
    }
  }
  return {
    detail: i18n.t("activity.incidents.guidance.authorization"),
    action: {
      kind: "settings",
      label: i18n.t("activity.incidents.action.reauthorize"),
      accountId: incident.account_id,
    },
  }
}

/**
 * The next step for an open incident, in the terms of what its category needs. A rule action is
 * offered only while the rule still exists.
 */
export function incidentGuidance(i18n: I18n, incident: Incident, rule: IncidentRuleState | null): IncidentGuidance {
  const { t } = i18n
  const ruleId = rule ? incident.rule_id : null
  if (AUTHORIZATION.has(incident.category)) return authorizationGuidance(i18n, incident, ruleId, rule)
  if (STOPPED.has(incident.category)) {
    return {
      detail: t("activity.incidents.guidance.stopped"),
      action: ruleAction("rule", ruleId, t("activity.incidents.action.review")),
    }
  }
  if (RETRYING.has(incident.category)) return { detail: t("activity.incidents.guidance.retrying"), action: null }
  if (incident.category === "conflict") {
    return {
      detail: t("activity.incidents.guidance.conflict"),
      action: ruleAction("blocked", ruleId, t("activity.incidents.action.seeBlocked")),
    }
  }
  return { detail: null, action: ruleAction("rule", ruleId, t("activity.incidents.action.review")) }
}

const RESOLUTIONS: Record<NonNullable<Incident["resolution"]>, MessageKey> = {
  sync_succeeded: "activity.incidents.resolution.syncSucceeded",
  blocks_cleared: "activity.incidents.resolution.blocksCleared",
  rule_removed: "activity.incidents.resolution.ruleRemoved",
  access_restored: "activity.incidents.resolution.accessRestored",
}

/** Why a resolved incident closed; null when it closed before the reason was recorded. */
export function incidentResolution(i18n: I18n, incident: Incident): string | null {
  return incident.resolution ? i18n.t(RESOLUTIONS[incident.resolution]) : null
}

/** When a resolved incident closed; older ones only know when they were last updated. */
export function incidentClosedAt(incident: Incident): string {
  return incident.resolved_at ?? incident.updated_at
}

/** How many incidents still need attention; Activity's Incidents tab counts them. */
export function openIncidentCount(incidents: Incident[]): number {
  return incidents.filter((incident) => incident.state === "open").length
}

/** A resolved incident's rule, while it exists, so its history shows the runs around it. */
export function resolvedFollowUp(i18n: I18n, incident: Incident, rule: IncidentRuleState | null): IncidentAction | null {
  if (incident.state === "open" || !rule || !incident.rule_id) return null
  return { kind: "history", ruleId: incident.rule_id, label: i18n.t("activity.incidents.action.seeActivity") }
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
  /** The fix while open; the rule's history once resolved. */
  action: IncidentAction | null
  /** The troubleshooting section for an open incident the administrator must fix. */
  fixUrl: string | null
}

export function incidentDetail(i18n: I18n, incident: Incident, rule: IncidentRuleState | null): IncidentDetail {
  // An unrecognised reason explains nothing, so the details leave it out.
  const known = causeOf(incident)
  const cause = known === "unknown" ? null : known
  if (incident.state !== "open") {
    const explanation = incidentResolution(i18n, incident)
    return { explanation, cause, action: resolvedFollowUp(i18n, incident, rule), fixUrl: null }
  }
  const { detail, action } = incidentGuidance(i18n, incident, rule)
  return { explanation: detail, cause, action, fixUrl: howToFixUrl(cause) }
}
