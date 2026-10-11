import { incidentText } from "@/i18n/incident-text"
import type { I18n } from "@/i18n/translator"
import { activitySearch } from "@/lib/activity-location"
import { causeOf, causeText, isAdministratorCause, retryTiming, type Cause } from "@/lib/causes"
import { providerWords } from "@/lib/providers"
import type { Dashboard, InstallationHealth, RunningWork, ServerProblem } from "@/lib/api"
import type { AppView, SettingsTab } from "@/lib/navigation"

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

export type HealthAction = { label: string; view: AppView; ruleId?: string; search?: string; settingsTab?: SettingsTab }

/** A problem the hero lists under the main one, in a few words. */
type OtherProblem = { tone: OverviewTone; summary: string; action: HealthAction | null }

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

/** The server's verdict, translated to the Overview's tone vocabulary; the Overview never derives its own (ADR 0024). */
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
 * its provider, or another open incident to review. Blocked events come from the dashboard instead.
 */
type RuleProblem = {
  ruleId: string
  name: string
  detail: string
  kind: "stopped" | "waiting" | "review"
  /** Why the provider failed, when it did (ADR 0031). */
  cause: Cause | null
  /** The Provider Kind that failed, when the server knows it. */
  provider: string | null
  /** When a Cause that fixes itself was last and will next be tried, as far as is known. */
  timing: string | null
}

/** The server's per-rule problems in the Overview's words. */
function ruleProblemsOf(
  i18n: I18n,
  dashboard: Pick<Dashboard, "problems" | "next_pass_at">,
  ruleName: (ruleId: string) => string | null,
  now: number,
): RuleProblem[] {
  const nextPassAt = dashboard.next_pass_at ?? null
  return dashboard.problems.flatMap((problem): RuleProblem[] => {
    if (problem.rule_id === null || problem.kind === "blocked" || problem.kind === "stalled") return []
    const name = ruleName(problem.rule_id) ?? ""
    const kind = problem.kind === "overdue" ? "review" : problem.kind
    return [
      {
        ruleId: problem.rule_id,
        name,
        detail: problemDetail(i18n, problem, now),
        kind,
        cause: causeOf(problem),
        provider: problem.provider ?? null,
        timing: retryTiming(i18n, problem, nextPassAt, now),
      },
    ]
  })
}

/** What the problem says, then when it began or the rule last synced. */
function problemDetail(i18n: I18n, problem: ServerProblem, now: number): string {
  // A problem an Incident explains carries its message; the others keep the server's English.
  const summary = sentence(incidentText(i18n, problem))
  if (!problem.since) return summary
  const key = problem.kind === "overdue" ? "overview.health.problemLastSync" : "overview.health.problemFirstSeen"
  return i18n.t(key, { summary, relative: i18n.format.relative(problem.since, now) })
}

type Problem = Omit<OverviewHealth, "facts" | "others"> & { summary: string }

/** Who reads the Overview: an administrator fixes the installation's own Causes. */
type Reader = { administrator: boolean }

/** What the Overview knows beyond the dashboard: its rules' names, and whether its reader administers. */
export type OverviewContext = { ruleName?: (ruleId: string) => string | null; administrator?: boolean }

function reauthorizeInSettings(i18n: I18n): HealthAction {
  return { label: i18n.t("overview.health.action.reauthorizeInSettings"), view: "settings", settingsTab: "connections" }
}

function reviewRulesAction(i18n: I18n): HealthAction {
  return { label: i18n.t("overview.health.action.reviewRules"), view: "rules" }
}

function openActivityAction(i18n: I18n): HealthAction {
  return { label: i18n.t("overview.health.action.openActivity"), view: "activity" }
}

function ruleAction(i18n: I18n, problem: RuleProblem): HealthAction {
  return { label: i18n.t("overview.health.action.reviewThisRule"), view: "rules", ruleId: problem.ruleId }
}

type ProblemsByKind = (kind: RuleProblem["kind"]) => RuleProblem[]

function stalledProblem(i18n: I18n, dashboard: Dashboard): Problem | null {
  if (!dashboard.problems.some((problem) => problem.kind === "stalled")) return null
  return {
    tone: "stopped",
    headline: i18n.t("overview.health.stalled.title"),
    title: "",
    detail: i18n.t("overview.health.stalled.detail"),
    action: null,
    summary: i18n.t("overview.health.stalled.title"),
  }
}

/** An administrator's Cause, and the provider that raised it when every problem names the same one. */
type Fault = { cause: Cause; provider: string | null }

/** The provider every one of these problems names, if they all name the same one. */
function sharedProvider(problems: RuleProblem[]): string | null {
  const [first] = problems
  return first && problems.every((problem) => problem.provider === first.provider) ? first.provider : null
}

/** The administrator's Cause every one of these problems shares, if they share one. */
function administratorCause(problems: RuleProblem[]): Cause | null {
  const [first] = problems
  if (!first || !isAdministratorCause(first.cause)) return null
  return problems.every((problem) => problem.cause === first.cause) ? first.cause : null
}

/**
 * Rules an administrator's Cause stopped. The User reads only that their calendar is temporarily
 * unavailable, with Check access to try again, so nothing sends them to the administrator; an
 * administrator is sent to People, where the fix is.
 */
function administratorStopped(i18n: I18n, headline: string, fault: Fault, reader: Reader): Problem {
  const { cause, provider } = fault
  const words = providerWords(i18n, provider)
  if (reader.administrator) {
    const likely = causeText(i18n, cause, provider)
    const title = i18n.t("overview.health.administratorCause.administratorTitle")
    return {
      tone: "stopped",
      headline,
      title,
      detail: i18n.t("overview.health.administratorCause.administratorDetail", { ...words, cause: likely }),
      action: { label: i18n.t("overview.health.action.openPeople"), view: "people" },
      summary: title,
    }
  }
  const title = i18n.t("overview.health.administratorCause.title")
  return {
    tone: "stopped",
    headline,
    title,
    detail: i18n.t("overview.health.administratorCause.detail", words),
    action: { label: i18n.t("overview.health.action.checkAccess"), view: "settings", settingsTab: "connections" },
    summary: title,
  }
}

function stoppedProblem(i18n: I18n, dashboard: Dashboard, of: ProblemsByKind, reader: Reader): Problem | null {
  const stopped = of("stopped")
  if (stopped.length === 0) return null
  const headline = i18n.t("overview.health.stoppedHeadline", { count: stopped.length })
  const byAdministrator = administratorCause(stopped)
  if (byAdministrator) {
    return administratorStopped(i18n, headline, { cause: byAdministrator, provider: sharedProvider(stopped) }, reader)
  }
  // Disconnected, or no longer accepted by its provider: either way the fix is to reauthorize.
  const unauthorized = dashboard.disconnected_accounts + dashboard.lapsed_accounts
  if (unauthorized > 0) {
    const title = i18n.t("overview.health.disconnectedTitle", { count: unauthorized })
    return {
      tone: "stopped",
      headline,
      title,
      detail: i18n.t("overview.health.disconnectedDetail"),
      action: reauthorizeInSettings(i18n),
      summary: title,
    }
  }
  const named = stopped.length === 1 && stopped[0]?.name ? stopped[0] : null
  if (!named) {
    return {
      tone: "stopped",
      headline,
      title: "",
      detail: i18n.t("overview.health.stoppedGenericDetail"),
      action: reviewRulesAction(i18n),
      summary: headline,
    }
  }
  return {
    tone: "stopped",
    headline,
    title: named.name,
    detail: [
      i18n.t("overview.health.stoppedNamedDetail", { detail: named.detail }),
      ...(named.cause === "calendar_forbidden" || named.cause === "calendar_not_found"
        ? [i18n.t("overview.health.chooseAnotherCalendar")]
        : []),
    ].join(" "),
    action: ruleAction(i18n, named),
    summary: i18n.t("overview.health.ruleStoppedSyncing", { name: named.name }),
  }
}

function reviewProblem(i18n: I18n, of: ProblemsByKind): Problem | null {
  const review = of("review")
  const [named] = review
  if (!named) return null
  const others = review.length - 1
  return {
    tone: "review",
    headline: i18n.t("overview.health.reviewHeadline"),
    title: named.name,
    detail:
      others > 0
        ? i18n.t("overview.health.reviewDetailWithOthers", { detail: named.detail, count: others })
        : named.detail,
    action: ruleAction(i18n, named),
    summary: i18n.t("overview.health.ruleNeedsLook", { name: named.name }),
  }
}

// A block leaves the rule running; it becomes an incident only if the daily check still finds it.
function blockedProblem(i18n: I18n, dashboard: Dashboard): Problem | null {
  if (dashboard.blocked_events <= 0 || dashboard.blocked_entry_id === null) return null
  const count = dashboard.blocked_events
  return {
    tone: "review",
    headline: i18n.t("overview.health.blockedHeadline", { count }),
    title: "",
    detail: i18n.t("overview.health.blockedDetail", { count }),
    action: {
      label: i18n.t("overview.health.blockedAction", { count }),
      view: "activity",
      search: activitySearch({
        ruleId: dashboard.blocked_rule_id ?? "",
        show: "blocked",
        entryId: dashboard.blocked_entry_id,
      }),
    },
    summary: i18n.t("overview.health.blockedSummary", { count }),
  }
}

/**
 * Why one rule waits, with when it was tried. Only an administrator reads that it is a quota they
 * raise; the User reads that the provider is limiting requests, as for any other wait.
 */
function waitingDetail(i18n: I18n, named: RuleProblem, reader: Reader): string {
  const words = providerWords(i18n, named.provider)
  if (reader.administrator && named.cause && isAdministratorCause(named.cause)) {
    return i18n.t("overview.health.administratorCause.administratorWaiting", {
      ...words,
      cause: causeText(i18n, named.cause, named.provider),
    })
  }
  const detail = i18n.t("overview.health.waitingDetailNamed", { ...words, detail: named.detail })
  return named.timing ? `${detail} ${named.timing}` : detail
}

function waitingProblem(i18n: I18n, of: ProblemsByKind, reader: Reader): Problem | null {
  const waiting = of("waiting")
  if (waiting.length === 0) return null
  const named = waiting.length === 1 ? waiting[0] : null
  const words = providerWords(i18n, sharedProvider(waiting))
  return {
    tone: "waiting",
    headline: i18n.t("overview.health.waitingHeadline", words),
    title: named?.name ?? "",
    detail: named
      ? waitingDetail(i18n, named, reader)
      : i18n.t("overview.health.waitingDetailGeneric", { ...words, count: waiting.length }),
    action: null,
    summary: named
      ? i18n.t("overview.health.ruleWaitingForProvider", { ...words, name: named.name })
      : i18n.t("overview.health.rulesWaitingForProvider", { ...words, count: waiting.length }),
  }
}

// Never healthy with an open incident, even one not described yet, such as while it loads.
function openIncidentsProblem(i18n: I18n, dashboard: Dashboard): Problem {
  return {
    tone: "review",
    headline: i18n.t("overview.health.openIncidentsHeadline"),
    title: "",
    detail: i18n.t("overview.health.openIncidentsDetail", { count: dashboard.open_incidents }),
    action: openActivityAction(i18n),
    summary: i18n.t("overview.health.openIncidentsSummary", { count: dashboard.open_incidents }),
  }
}

/** Every current problem, most urgent first. */
function problemsOf(i18n: I18n, dashboard: Dashboard, ruleProblems: RuleProblem[], reader: Reader): Problem[] {
  const of: ProblemsByKind = (kind) => ruleProblems.filter((problem) => problem.kind === kind)
  const problems = [
    stalledProblem(i18n, dashboard),
    stoppedProblem(i18n, dashboard, of, reader),
    reviewProblem(i18n, of),
    blockedProblem(i18n, dashboard),
    waitingProblem(i18n, of, reader),
  ].filter((problem): problem is Problem => problem !== null)
  if (problems.length === 0 && dashboard.open_incidents > 0) problems.push(openIncidentsProblem(i18n, dashboard))
  return problems
}

type HealthFacts = { running: string[]; stopped: string[]; lastSync: string | null }

function healthFacts(i18n: I18n, dashboard: Dashboard, now: number): HealthFacts {
  const lastSync = dashboard.last_synced_at
    ? i18n.t("overview.health.lastSync", { relative: i18n.format.relative(dashboard.last_synced_at, now) })
    : null
  return {
    running: [
      i18n.t("overview.health.rulesRunning", { count: dashboard.enabled_rules }),
      lastSync ?? i18n.t("overview.health.notSyncedYet"),
    ],
    stopped: [
      dashboard.enabled_rules > 0
        ? i18n.t("overview.health.rulesStillRunning", { count: dashboard.enabled_rules })
        : i18n.t("overview.health.noRulesRunning"),
      lastSync ?? i18n.t("overview.health.waitingForRecovery"),
    ],
    lastSync,
  }
}

/** A health with no other problems below it. */
function onlyHealth(
  tone: OverviewTone,
  headline: string,
  detail: string,
  rest: Partial<Pick<OverviewHealth, "facts" | "action">> = {},
): OverviewHealth {
  return { tone, headline, title: "", detail, facts: rest.facts ?? [], action: rest.action ?? null, others: [] }
}

/** Before any rule can run: no account connected yet, or every account lost access. */
function accountSetupHealth(i18n: I18n, dashboard: Dashboard, tone: OverviewTone): OverviewHealth | null {
  const { t } = i18n
  if (dashboard.connected_accounts + dashboard.disconnected_accounts === 0) {
    return onlyHealth(tone, t("overview.health.setup.title"), t("overview.health.setup.detail"))
  }
  if (dashboard.connected_accounts === 0 && dashboard.stopped_rules === 0 && dashboard.open_incidents === 0) {
    return onlyHealth(tone, t("overview.health.reauthorizeSetup.title"), t("overview.health.reauthorizeSetup.detail"), {
      action: reauthorizeInSettings(i18n),
    })
  }
  return null
}

/**
 * The server can report attention before the client's per-rule problems explain why, such as
 * between the dashboard poll and the next one; a generic hero for that tone still tells the
 * truth instead of contradicting it with healthy, paused, or setup copy (ADR 0024).
 */
function genericAttentionHealth(i18n: I18n, tone: OverviewTone, facts: HealthFacts): OverviewHealth | null {
  const { t } = i18n
  if (tone === "stopped") {
    return onlyHealth(tone, t("overview.health.generic.stopped.title"), t("overview.health.generic.stopped.detail"), {
      action: reviewRulesAction(i18n),
      facts: facts.stopped,
    })
  }
  if (tone === "review") {
    return onlyHealth(tone, t("overview.health.generic.review.title"), t("overview.health.generic.review.detail"), {
      action: openActivityAction(i18n),
      facts: facts.running,
    })
  }
  if (tone === "waiting") {
    return onlyHealth(tone, t("overview.health.generic.waiting.title"), t("overview.health.generic.waiting.detail"), {
      facts: facts.running,
    })
  }
  return null
}

/** No problem: no rule yet, every rule paused or never started, or everything healthy. */
function quietHealth(i18n: I18n, dashboard: Dashboard, tone: OverviewTone, facts: HealthFacts): OverviewHealth {
  const { t } = i18n
  const review = reviewRulesAction(i18n)
  if (dashboard.sync_rules === 0) {
    return onlyHealth(tone, t("overview.health.noRules.title"), t("overview.health.noRules.detail"), {
      action: { label: t("overview.health.action.createRule"), view: "rules" },
    })
  }
  if (dashboard.enabled_rules > 0) {
    return onlyHealth(tone, t("overview.health.healthy.title"), t("overview.health.healthy.detail"), {
      facts: facts.running,
    })
  }
  // A rule that has synced before was paused on purpose; one that never has is still being set up.
  if (facts.lastSync) {
    return onlyHealth(tone, t("overview.health.paused.title"), t("overview.health.paused.detail"), {
      facts: [t("overview.health.rulesNotRunning", { count: dashboard.sync_rules }), facts.lastSync],
      action: review,
    })
  }
  return onlyHealth(tone, t("overview.health.neverRun.title"), t("overview.health.neverRun.detail"), { action: review })
}

/**
 * One health model for the Overview, so the headline, facts, and next action can never disagree.
 * The server decides the tone (ADR 0024); the most urgent problem leads, and the hero lists the
 * rest below it.
 */
export function overviewHealth(
  i18n: I18n,
  dashboard: Dashboard,
  now: number = Date.now(),
  { ruleName = () => null, administrator = false }: OverviewContext = {},
): OverviewHealth {
  const reader: Reader = { administrator }
  const tone = TONE_OF[dashboard.status]
  const setup = accountSetupHealth(i18n, dashboard, tone)
  if (setup) return setup
  const facts = healthFacts(i18n, dashboard, now)
  const ruleProblems = ruleProblemsOf(i18n, dashboard, ruleName, now)
  const [main, ...rest] = problemsOf(i18n, dashboard, ruleProblems, reader)
  if (main) {
    return {
      tone,
      headline: main.headline,
      title: main.title,
      detail: main.detail,
      action: main.action,
      facts: main.tone === "stopped" ? facts.stopped : facts.running,
      others: rest.map(({ tone: otherTone, summary, action }) => ({ tone: otherTone, summary, action })),
    }
  }
  return genericAttentionHealth(i18n, tone, facts) ?? quietHealth(i18n, dashboard, tone, facts)
}
