import { activitySearch } from "@/lib/activity-location"
import type { Dashboard, InstallationHealth, RunningWork, ServerProblem } from "@/lib/api"
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

/** The server's verdict, translated to the Overview's tone vocabulary; the Overview never derives its own (ADR 0023). */
const TONE_OF: Record<InstallationHealth, OverviewTone> = {
  stalled: "stopped",
  stopped: "stopped",
  review: "review",
  waiting: "waiting",
  paused: "paused",
  setup: "setup",
  healthy: "healthy",
}

// Incident summaries are written with or without a closing period.
function sentence(text: string): string {
  return /[.!?]$/.test(text) ? text : `${text}.`
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

/** The server's per-rule problems in the Overview's words. */
export function ruleProblemsOf(
  problems: ServerProblem[],
  ruleName: (ruleId: string) => string | null,
  now: number,
): RuleProblem[] {
  return problems.flatMap((problem): RuleProblem[] => {
    if (problem.rule_id === null || problem.kind === "blocked" || problem.kind === "stalled") return []
    const name = ruleName(problem.rule_id) ?? ""
    const since = problem.since
      ? problem.kind === "overdue"
        ? ` Last sync ${relativeTime(problem.since, now)}.`
        : ` First seen ${relativeTime(problem.since, now)}.`
      : ""
    const kind = problem.kind === "overdue" ? "review" : problem.kind
    return [{ ruleId: problem.rule_id, name, detail: `${sentence(problem.summary)}${since}`, kind }]
  })
}

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

/** Every current problem, most urgent first. */
function problemsOf(dashboard: Dashboard, ruleProblems: RuleProblem[]): Problem[] {
  const problems: Problem[] = []
  const of = (kind: RuleProblem["kind"]) => ruleProblems.filter((problem) => problem.kind === kind)

  if (dashboard.problems.some((problem) => problem.kind === "stalled")) {
    problems.push({
      tone: "stopped",
      headline: "Synchronization stopped running",
      title: "",
      detail:
        "Calendar Ghost has not checked your calendars recently. Restart the service to resume. Events already synced stay where they are.",
      action: null,
      summary: "Synchronization stopped running",
    })
  }

  const stoppedCount = of("stopped").length
  const stoppedHeadline = stoppedCount === 1 ? "A rule stopped syncing" : `${stoppedCount} rules stopped syncing`

  if (dashboard.disconnected_accounts > 0 && stoppedCount > 0) {
    const title = `${count(dashboard.disconnected_accounts, "Google account")} ${dashboard.disconnected_accounts === 1 ? "needs" : "need"} reauthorization`
    problems.push({
      tone: "stopped",
      headline: stoppedHeadline,
      title,
      detail: `Access was removed or expired, so its rules write nothing until you reauthorize. ${ALREADY_SYNCED}`,
      action: { label: "Reauthorize in Settings", view: "settings" },
      summary: title,
    })
  } else if (stoppedCount > 0) {
    const stopped = of("stopped")
    const named = stoppedCount === 1 && stopped[0].name ? stopped[0] : null
    problems.push({
      tone: "stopped",
      headline: stoppedHeadline,
      title: named?.name ?? "",
      detail: named
        ? `${named.detail} It writes nothing until it is fixed. ${ALREADY_SYNCED}`
        : `Stopped rules write nothing until they are fixed. ${ALREADY_SYNCED}`,
      action: named ? ruleAction(named) : { label: "Review rules", view: "rules" },
      summary: named ? `${named.name} stopped syncing` : stoppedHeadline,
    })
  }

  const review = of("review")
  if (review.length > 0) {
    const [named] = review
    const others = review.length - 1
    problems.push({
      tone: "review",
      headline: "A rule needs a look",
      title: named.name,
      detail: others > 0 ? `${named.detail} ${count(others, "other problem")} also ${others === 1 ? "needs" : "need"} a look.` : named.detail,
      action: ruleAction(named),
      summary: `${named.name} needs a look`,
    })
  }

  // A block leaves the rule running; it becomes an incident only if the daily check still finds it.
  if (dashboard.blocked_events > 0 && dashboard.blocked_entry_id !== null) {
    const one = dashboard.blocked_events === 1
    problems.push({
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
    })
  }

  const waiting = of("waiting")
  if (waiting.length > 0) {
    const named = waiting.length === 1 ? waiting[0] : null
    problems.push({
      tone: "waiting",
      headline: "Waiting for Google",
      title: named?.name ?? "",
      detail: named
        ? `${named.detail} ${RETRYING}`
        : `Google Calendar is limiting or failing requests for ${count(waiting.length, "rule")}. ${RETRYING}`,
      action: null,
      summary: named ? `${named.name} is waiting for Google` : `${count(waiting.length, "rule")} waiting for Google`,
    })
  }

  // Never healthy with an open incident, even one not described yet, such as while it loads.
  if (problems.length === 0 && dashboard.open_incidents > 0) {
    problems.push({
      tone: "review",
      headline: "Something needs a look",
      title: "",
      detail: `${count(dashboard.open_incidents, "problem")} kept happening. Activity explains what happened and what to do.`,
      action: { label: "Open Activity", view: "activity" },
      summary: `${count(dashboard.open_incidents, "open problem")} in Activity`,
    })
  }
  return problems
}

/**
 * One health model for the Overview, so the headline, facts, and next action can never disagree.
 * The server decides the tone (ADR 0023); the most urgent problem leads, and the hero lists the
 * rest below it.
 */
export function overviewHealth(
  dashboard: Dashboard,
  now: number = Date.now(),
  ruleName: (ruleId: string) => string | null = () => null,
): OverviewHealth {
  const ruleProblems = ruleProblemsOf(dashboard.problems, ruleName, now)
  const accounts = dashboard.connected_accounts + dashboard.disconnected_accounts
  const lastSync = dashboard.last_synced_at ? `Last sync ${relativeTime(dashboard.last_synced_at, now)}` : null
  const runningFacts = [`${count(dashboard.enabled_rules, "rule")} running`, lastSync ?? "Not synced yet"]

  if (accounts === 0) {
    return {
      tone: TONE_OF[dashboard.status],
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
      tone: TONE_OF[dashboard.status],
      headline: "Reauthorize your Google account",
      title: "",
      detail: "Access was removed or expired. Renew it in Settings before creating or running rules.",
      facts: [],
      action: { label: "Reauthorize in Settings", view: "settings" },
      others: [],
    }
  }
  const [main, ...rest] = problemsOf(dashboard, ruleProblems)
  const stoppedFacts = [
    dashboard.enabled_rules > 0 ? `${count(dashboard.enabled_rules, "rule")} still running` : "No rules running",
    lastSync ?? "Waiting for recovery",
  ]
  if (main) {
    return {
      tone: TONE_OF[dashboard.status],
      headline: main.headline,
      title: main.title,
      detail: main.detail,
      action: main.action,
      facts: main.tone === "stopped" ? stoppedFacts : runningFacts,
      others: rest.map(({ tone, summary, action }) => ({ tone, summary, action })),
    }
  }
  // The server can report attention before the client's per-rule problems explain why, such as
  // between the dashboard poll and the next one; a generic hero for that tone still tells the
  // truth instead of contradicting it with healthy, paused, or setup copy (ADR 0023).
  const tone = TONE_OF[dashboard.status]
  if (tone === "stopped" || tone === "review" || tone === "waiting") {
    const generic = {
      stopped: {
        headline: "Synchronization needs attention",
        detail: "A rule stopped syncing. Rules shows which one and what to do. Events already synced stay where they are.",
        action: { label: "Review rules", view: "rules" } as HealthAction | null,
        facts: stoppedFacts,
      },
      review: {
        headline: "Something needs a look",
        detail: "Activity explains what happened and what to do.",
        action: { label: "Open Activity", view: "activity" } as HealthAction | null,
        facts: runningFacts,
      },
      waiting: {
        headline: "Waiting for the calendar provider",
        detail: "Calendar Ghost retries by itself and catches up afterwards.",
        action: null as HealthAction | null,
        facts: runningFacts,
      },
    }[tone]
    return {
      tone,
      headline: generic.headline,
      title: "",
      detail: generic.detail,
      action: generic.action,
      facts: generic.facts,
      others: [],
    }
  }
  if (dashboard.sync_rules === 0) {
    return {
      tone: TONE_OF[dashboard.status],
      headline: "Create your first rule",
      title: "",
      detail: "Choose a source and a destination calendar, then preview what the rule will write.",
      facts: [],
      action: { label: "Create a rule", view: "rules" },
      others: [],
    }
  }
  if (dashboard.enabled_rules === 0) {
    // A rule that has synced before was paused on purpose; one that never has is still being set up.
    if (lastSync) {
      return {
        tone: TONE_OF[dashboard.status],
        headline: "Synchronization is paused",
        title: "",
        detail: "Nothing is written to your calendars until you start a rule again.",
        facts: [`${count(dashboard.sync_rules, "rule")} not running`, lastSync],
        action: { label: "Review rules", view: "rules" },
        others: [],
      }
    }
    return {
      tone: TONE_OF[dashboard.status],
      headline: "No rule is synchronizing",
      title: "",
      detail: "Preview a rule, then enable it to start writing to its destination calendar.",
      facts: [],
      action: { label: "Review rules", view: "rules" },
      others: [],
    }
  }
  return {
    tone: TONE_OF[dashboard.status],
    headline: "Synchronization is healthy",
    title: "",
    detail: "Calendar Ghost checks your calendars for changes every five minutes.",
    facts: runningFacts,
    action: null,
    others: [],
  }
}
