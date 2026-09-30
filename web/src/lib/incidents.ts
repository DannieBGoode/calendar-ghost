import type { Incident } from "@/lib/api"

/** What the administrator can do about an open incident, if anything. */
export type IncidentAction =
  | { kind: "settings"; label: string }
  | { kind: "rule"; ruleId: string; label: string }
  | { kind: "blocked"; ruleId: string; label: string }

export type IncidentGuidance = { detail: string | null; action: IncidentAction | null }

/** What an incident's rule looks like now; null when the incident has no rule or it is gone. */
export type IncidentRuleState = { accountsConnected: boolean }

const AUTHORIZATION = new Set(["authentication", "authorization"])
const STOPPED = new Set(["permanent", "infrastructure"])
const RETRYING = new Set(["rate_limit", "temporary"])

/**
 * The next step for an open incident, in the terms of what its category needs. A rule action is
 * offered only while the rule still exists.
 */
export function incidentGuidance(incident: Incident, rule: IncidentRuleState | null): IncidentGuidance {
  const ruleId = rule ? incident.rule_id : null
  if (AUTHORIZATION.has(incident.category)) {
    // Reauthorizing renews access but leaves the rule stopped; only its recovery closes this.
    if (ruleId && rule?.accountsConnected) {
      return {
        detail: "Google access is renewed, but the rule stays stopped until it is recovered.",
        action: { kind: "rule", ruleId, label: "Recover this rule" },
      }
    }
    return {
      detail: "Nothing is written until the Google account is reauthorized. Existing events stay where they are.",
      action: { kind: "settings", label: "Reauthorize in Settings" },
    }
  }
  if (STOPPED.has(incident.category)) {
    return {
      detail: "The rule is stopped and writes nothing until it is recovered.",
      action: ruleId ? { kind: "rule", ruleId, label: "Review this rule" } : null,
    }
  }
  if (RETRYING.has(incident.category)) {
    return {
      detail: "Nothing to do now. Calendar Sync keeps retrying and closes this after the next successful sync.",
      action: null,
    }
  }
  if (incident.category === "conflict") {
    return {
      detail: "The rest of the rule keeps syncing. This closes when a daily check finds nothing still blocked.",
      action: ruleId ? { kind: "blocked", ruleId, label: "See blocked events" } : null,
    }
  }
  return { detail: null, action: ruleId ? { kind: "rule", ruleId, label: "Review this rule" } : null }
}

const RESOLUTIONS: Record<NonNullable<Incident["resolution"]>, string> = {
  sync_succeeded: "Resolved by a successful sync.",
  blocks_cleared: "Resolved when the daily check found nothing still blocked.",
  rule_removed: "Closed when the rule was removed.",
}

/** Why a resolved incident closed; null when it closed before the reason was recorded. */
export function incidentResolution(incident: Incident): string | null {
  return incident.resolution ? RESOLUTIONS[incident.resolution] : null
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
