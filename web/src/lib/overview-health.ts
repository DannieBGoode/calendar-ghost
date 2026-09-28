import type { Dashboard } from "@/lib/api"
import type { AppView } from "@/lib/navigation"
import { relativeTime } from "@/lib/relative-time"

export type OverviewTone = "setup" | "healthy" | "attention"

export type OverviewHealth = {
  tone: OverviewTone
  headline: string
  title: string
  detail: string
  badge: string
  action: { label: string; view: AppView; ruleId?: string } | null
}

/** The rule an attention state is about, so the Overview can name it and link straight to it. */
export type AttentionRule = { ruleId: string; name: string; detail: string }

function count(value: number, singular: string, plural = `${singular}s`): string {
  return `${value} ${value === 1 ? singular : plural}`
}

/**
 * One health model for the Overview, so the headline, strip, badge, and next action can never
 * disagree. Attention outranks setup: a stopped rule matters more than an unfinished one.
 */
export function overviewHealth(
  dashboard: Dashboard,
  now: number = Date.now(),
  attention: AttentionRule | null = null,
): OverviewHealth {
  const accounts = dashboard.connected_accounts + dashboard.disconnected_accounts
  if (accounts === 0) {
    return {
      tone: "setup",
      headline: "Set up your first synchronization",
      title: "Ready for setup",
      detail: "The service is running and waiting for a Google account.",
      badge: "Setup",
      action: null,
    }
  }
  if (dashboard.disconnected_accounts > 0 && dashboard.stopped_rules > 0) {
    return {
      tone: "attention",
      headline: "Synchronization needs attention",
      title: `${count(dashboard.disconnected_accounts, "Google account")} ${dashboard.disconnected_accounts === 1 ? "needs" : "need"} reauthorization`,
      detail: `${count(dashboard.stopped_rules, "rule")} stopped until access is renewed. Existing events stay where they are.`,
      badge: "Needs attention",
      action: { label: "Reauthorize in Settings", view: "settings" },
    }
  }
  if (attention && (dashboard.open_incidents > 0 || dashboard.stopped_rules > 0)) {
    const others = Math.max(dashboard.open_incidents, dashboard.stopped_rules) - 1
    return {
      tone: "attention",
      headline: "Synchronization needs attention",
      title: `${attention.name} needs attention`,
      detail: others > 0 ? `${attention.detail} ${count(others, "other problem")} also ${others === 1 ? "needs" : "need"} a look.` : attention.detail,
      badge: "Needs attention",
      action: { label: "Review this rule", view: "rules", ruleId: attention.ruleId },
    }
  }
  if (dashboard.open_incidents > 0) {
    return {
      tone: "attention",
      headline: "Synchronization needs attention",
      title: `${count(dashboard.open_incidents, "incident")} ${dashboard.open_incidents === 1 ? "needs" : "need"} attention`,
      detail: "Activity explains what happened and how to recover.",
      badge: "Needs attention",
      action: { label: "Open Activity", view: "activity" },
    }
  }
  if (dashboard.stopped_rules > 0) {
    return {
      tone: "attention",
      headline: "Synchronization needs attention",
      title: `${count(dashboard.stopped_rules, "rule")} stopped`,
      detail: "A stopped rule writes nothing until it is recovered.",
      badge: "Needs attention",
      action: { label: "Review rules", view: "rules" },
    }
  }
  if (dashboard.sync_rules === 0) {
    return {
      tone: "setup",
      headline: "Create your first rule",
      title: "No calendars are synchronizing yet",
      detail: "Choose a source and a destination calendar, then preview what the rule will write.",
      badge: "Setup",
      action: { label: "Create a rule", view: "rules" },
    }
  }
  if (dashboard.enabled_rules === 0) {
    return {
      tone: "setup",
      headline: "No rule is synchronizing",
      title: "Every rule is paused or waiting to be enabled",
      detail: "Preview a rule, then enable it to start writing to its destination calendar.",
      badge: "Not running",
      action: { label: "Review rules", view: "rules" },
    }
  }
  return {
    tone: "healthy",
    headline: "Synchronization is healthy",
    title: `${count(dashboard.enabled_rules, "rule")} running normally`,
    detail: dashboard.last_synced_at
      ? `Last sync ${relativeTime(dashboard.last_synced_at, now)}. Calendar Sync checks for changes every five minutes.`
      : "The first sync runs within five minutes.",
    badge: "Healthy",
    action: null,
  }
}
