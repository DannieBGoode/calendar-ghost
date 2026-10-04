import { activitySearch } from "@/lib/activity-location"
import type { Dashboard, RunningWork } from "@/lib/api"
import type { AppView } from "@/lib/navigation"
import { relativeTime } from "@/lib/relative-time"

/**
 * The Overview's health, most urgent first:
 * - stopped: a rule is suspended until the administrator acts, such as reauthorizing Google.
 * - review: rules keep running, but events were blocked or a problem kept happening.
 * - waiting: Google is limiting or failing requests; rules retry by themselves, nothing to do.
 * - paused: rules exist and have synced before, but none is running now.
 * - setup: nothing is synchronizing yet.
 * - healthy: everything is running and up to date.
 */
export type OverviewTone = "stopped" | "review" | "waiting" | "paused" | "setup" | "healthy"

export type HealthAction = { label: string; view: AppView; ruleId?: string; search?: string }

/** A problem the hero lists under the main one, in a few words. */
export type OtherProblem = { tone: OverviewTone; summary: string; action: HealthAction | null }

export type OverviewHealth = {
  tone: OverviewTone
  headline: string
  /** What the state is about, such as the affected rule, under the headline; empty when the headline says it all. */
  title: string
  detail: string
  /**
   * Short facts below the detail, each saying something the headline and detail do not. Setup has
   * none: its Getting started steps already show progress.
   */
  facts: string[]
  action: HealthAction | null
  /** Every other problem, most urgent first, so one never hides another. */
  others: OtherProblem[]
}

/**
 * The service stores a rule as disabled from the moment its removal starts, so the dashboard
 * counts it as stopped. A removal still running in this session is not a failure.
 */
export function withoutRunningRemovals(
  dashboard: Dashboard,
  rules: { id: string; state: string }[],
  removing: ReadonlySet<string>,
): Dashboard {
  const running = rules.filter((rule) => removing.has(rule.id) && rule.state === "disabled").length
  if (running === 0) return dashboard
  const stopped = Math.max(0, dashboard.stopped_rules - running)
  return {
    ...dashboard,
    stopped_rules: stopped,
    health: stopped === 0 && dashboard.open_incidents === 0 ? "healthy" : dashboard.health,
  }
}

/**
 * The rules the Overview lists: those working right now first, then enabled ones, the rest in
 * their order. Sorting precedes the limit so running work is never cut off.
 */
export function overviewRules<T extends { id: string; state: string; running: RunningWork | null }>(
  rules: T[],
  removing: ReadonlySet<string>,
  limit: number,
): T[] {
  const rank = (rule: T) => (rule.running || removing.has(rule.id) ? 0 : rule.state === "enabled" ? 1 : 2)
  return [...rules].sort((a, b) => rank(a) - rank(b)).slice(0, limit)
}

/**
 * A rule-level problem the Overview can name: stopped until the administrator acts, waiting on
 * Google, or another open incident to review. Blocked events come from the dashboard instead.
 */
export type RuleProblem = { ruleId: string; name: string; detail: string; kind: "stopped" | "waiting" | "review" }

type Problem = Omit<OverviewHealth, "facts" | "others"> & { summary: string }

function count(value: number, singular: string, plural = `${singular}s`): string {
  return `${value} ${value === 1 ? singular : plural}`
}

const ALREADY_SYNCED = "Events already synced stay where they are."
const RETRYING =
  "Wait for Google to respond: Calendar Ghost retries by itself and catches up afterwards. If it lasts more than a day, check the Google Workspace Status Dashboard."

function ruleAction(problem: RuleProblem): HealthAction {
  return { label: "Review this rule", view: "rules", ruleId: problem.ruleId }
}

function stoppedHeadline(dashboard: Dashboard): string {
  return dashboard.stopped_rules === 1 ? "A rule stopped syncing" : `${dashboard.stopped_rules} rules stopped syncing`
}

/** Stopped rules, either because their Google account needs reauthorization or for their own reason. */
function stoppedProblem(dashboard: Dashboard, stopped: RuleProblem[]): Problem | null {
  if (dashboard.disconnected_accounts > 0 && dashboard.stopped_rules > 0) return reauthorizationProblem(dashboard)
  if (dashboard.stopped_rules > 0) return stoppedRulesProblem(dashboard, stopped)
  return null
}

function reauthorizationProblem(dashboard: Dashboard): Problem {
  const title = `${count(dashboard.disconnected_accounts, "Google account")} ${dashboard.disconnected_accounts === 1 ? "needs" : "need"} reauthorization`
  return {
    tone: "stopped",
    headline: stoppedHeadline(dashboard),
    title,
    detail: `Access was removed or expired, so its rules write nothing until you reauthorize. ${ALREADY_SYNCED}`,
    action: { label: "Reauthorize in Settings", view: "settings" },
    summary: title,
  }
}

function stoppedRulesProblem(dashboard: Dashboard, stopped: RuleProblem[]): Problem {
  const headline = stoppedHeadline(dashboard)
  const named = dashboard.stopped_rules === 1 && stopped.length === 1 ? stopped[0] : null
  if (named) {
    return {
      tone: "stopped",
      headline,
      title: named.name,
      detail: `${named.detail} It writes nothing until it is fixed. ${ALREADY_SYNCED}`,
      action: ruleAction(named),
      summary: `${named.name} stopped syncing`,
    }
  }
  return {
    tone: "stopped",
    headline,
    title: "",
    detail: `Stopped rules write nothing until they are fixed. ${ALREADY_SYNCED}`,
    action: { label: "Review rules", view: "rules" },
    summary: headline,
  }
}

function reviewProblem(review: RuleProblem[]): Problem | null {
  const [named] = review
  if (!named) return null
  const others = review.length - 1
  return {
    tone: "review",
    headline: "A rule needs a look",
    title: named.name,
    detail: others > 0 ? `${named.detail} ${count(others, "other problem")} also ${others === 1 ? "needs" : "need"} a look.` : named.detail,
    action: ruleAction(named),
    summary: `${named.name} needs a look`,
  }
}

/** A block leaves the rule running; it becomes an incident only if the daily check still finds it. */
function blockedProblem(dashboard: Dashboard): Problem | null {
  if (dashboard.blocked_events <= 0 || dashboard.blocked_entry_id === null) return null
  const one = dashboard.blocked_events === 1
  return {
    tone: "review",
    headline: one ? "An event needs a look" : "Some events need a look",
    title: "",
    detail: `${count(dashboard.blocked_events, "event")} couldn't be synced and ${one ? "was" : "were"} left unchanged. Everything else is up to date.`,
    action: {
      label: one ? "See the blocked event" : "See blocked events",
      view: "activity",
      search: activitySearch({
        ruleId: dashboard.blocked_rule_id ?? "",
        show: "blocked",
        entryId: dashboard.blocked_entry_id,
      }),
    },
    summary: `${count(dashboard.blocked_events, "event")} couldn't be synced`,
  }
}

function waitingProblem(waiting: RuleProblem[]): Problem | null {
  if (waiting.length === 0) return null
  const named = waiting.length === 1 ? waiting[0] : null
  return {
    tone: "waiting",
    headline: "Waiting for Google",
    title: named?.name ?? "",
    detail: named
      ? `${named.detail} ${RETRYING}`
      : `Google Calendar is limiting or failing requests for ${count(waiting.length, "rule")}. ${RETRYING}`,
    action: null,
    summary: named ? `${named.name} is waiting for Google` : `${count(waiting.length, "rule")} waiting for Google`,
  }
}

function openIncidentsProblem(dashboard: Dashboard): Problem {
  return {
    tone: "review",
    headline: "Something needs a look",
    title: "",
    detail: `${count(dashboard.open_incidents, "problem")} kept happening. Activity explains what happened and what to do.`,
    action: { label: "Open Activity", view: "activity" },
    summary: `${count(dashboard.open_incidents, "open problem")} in Activity`,
  }
}

/** Every current problem, most urgent first. */
function problemsOf(dashboard: Dashboard, ruleProblems: RuleProblem[]): Problem[] {
  const of = (kind: RuleProblem["kind"]) => ruleProblems.filter((problem) => problem.kind === kind)
  const problems = [
    stoppedProblem(dashboard, of("stopped")),
    reviewProblem(of("review")),
    blockedProblem(dashboard),
    waitingProblem(of("waiting")),
  ].filter((problem) => problem !== null)
  // Never healthy with an open incident, even one not described yet, such as while it loads.
  if (problems.length === 0 && dashboard.open_incidents > 0) problems.push(openIncidentsProblem(dashboard))
  return problems
}

/** Setup that comes before any rule: connecting a Google account, or renewing the only access there was. */
function accountSetup(dashboard: Dashboard): OverviewHealth | null {
  const accounts = dashboard.connected_accounts + dashboard.disconnected_accounts
  if (accounts === 0) {
    return {
      tone: "setup",
      headline: "Set up your first synchronization",
      title: "",
      detail: "The service is running and waiting for a Google account.",
      facts: [],
      action: null,
      others: [],
    }
  }
  if (dashboard.connected_accounts === 0 && dashboard.stopped_rules === 0 && dashboard.open_incidents === 0) {
    return {
      tone: "setup",
      headline: "Reauthorize your Google account",
      title: "",
      detail: "Access was removed or expired. Renew it in Settings before creating or running rules.",
      facts: [],
      action: { label: "Reauthorize in Settings", view: "settings" },
      others: [],
    }
  }
  return null
}

function runningFacts(dashboard: Dashboard, lastSync: string | null): string[] {
  return [`${count(dashboard.enabled_rules, "rule")} running`, lastSync ?? "Not synced yet"]
}

function problemFacts(dashboard: Dashboard, main: Problem, lastSync: string | null): string[] {
  if (main.tone !== "stopped") return runningFacts(dashboard, lastSync)
  return [
    dashboard.enabled_rules > 0 ? `${count(dashboard.enabled_rules, "rule")} still running` : "No rules running",
    lastSync ?? "Waiting for recovery",
  ]
}

function problemHealth(main: Problem, rest: Problem[], facts: string[]): OverviewHealth {
  return {
    tone: main.tone,
    headline: main.headline,
    title: main.title,
    detail: main.detail,
    action: main.action,
    facts,
    others: rest.map(({ tone, summary, action }) => ({ tone, summary, action })),
  }
}

/** With no problem: still creating or enabling rules, paused on purpose, or healthy. */
function quietHealth(dashboard: Dashboard, lastSync: string | null): OverviewHealth {
  if (dashboard.sync_rules === 0) {
    return {
      tone: "setup",
      headline: "Create your first rule",
      title: "",
      detail: "Choose a source and a destination calendar, then preview what the rule will write.",
      facts: [],
      action: { label: "Create a rule", view: "rules" },
      others: [],
    }
  }
  if (dashboard.enabled_rules === 0) return notRunningHealth(dashboard, lastSync)
  return {
    tone: "healthy",
    headline: "Synchronization is healthy",
    title: "",
    detail: "Calendar Ghost checks your calendars for changes every five minutes.",
    facts: runningFacts(dashboard, lastSync),
    action: null,
    others: [],
  }
}

function notRunningHealth(dashboard: Dashboard, lastSync: string | null): OverviewHealth {
  // A rule that has synced before was paused on purpose; one that never has is still being set up.
  if (lastSync) {
    return {
      tone: "paused",
      headline: "Synchronization is paused",
      title: "",
      detail: "Nothing is written to your calendars until you start a rule again.",
      facts: [`${count(dashboard.sync_rules, "rule")} not running`, lastSync],
      action: { label: "Review rules", view: "rules" },
      others: [],
    }
  }
  return {
    tone: "setup",
    headline: "No rule is synchronizing",
    title: "",
    detail: "Preview a rule, then enable it to start writing to its destination calendar.",
    facts: [],
    action: { label: "Review rules", view: "rules" },
    others: [],
  }
}

/**
 * One health model for the Overview, so the headline, facts, and next action can never disagree.
 * The most urgent problem leads, and the hero lists the rest below it.
 */
export function overviewHealth(
  dashboard: Dashboard,
  now: number = Date.now(),
  ruleProblems: RuleProblem[] = [],
): OverviewHealth {
  const lastSync = dashboard.last_synced_at ? `Last sync ${relativeTime(dashboard.last_synced_at, now)}` : null
  const setup = accountSetup(dashboard)
  if (setup) return setup
  const [main, ...rest] = problemsOf(dashboard, ruleProblems)
  if (main) return problemHealth(main, rest, problemFacts(dashboard, main, lastSync))
  return quietHealth(dashboard, lastSync)
}
