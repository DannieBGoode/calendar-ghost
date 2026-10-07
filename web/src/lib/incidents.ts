import type { I18n } from "@/i18n/translator"
import type { MessageKey } from "@/i18n/types"
import type { ConnectedAccount, Incident } from "@/lib/api"

/** What the administrator can do about an open incident, if anything. */
export type IncidentAction =
  | { kind: "settings"; label: string; accountId: string | null }
  | { kind: "rule"; ruleId: string; label: string }
  | { kind: "blocked"; ruleId: string; label: string }

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

/** Open incidents lead Activity; resolved ones are evidence kept out of the way. */
export function splitIncidents(incidents: Incident[]): { open: Incident[]; resolved: Incident[] } {
  return {
    open: incidents.filter((incident) => incident.state === "open"),
    resolved: incidents.filter((incident) => incident.state !== "open"),
  }
}
