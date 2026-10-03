import type {
  AuditEntry,
  ConnectedAccount,
  Dashboard,
  DiscoveredCalendar,
  RecentChange,
  RuleSummary,
  RunOutcome,
} from "./api"
import type { RuleEndpoints } from "./use-rule-endpoints"

/**
 * Synthetic dashboard content for visual review. It is deliberately kept in the frontend and
 * only enabled by an explicit query parameter, so previewing the full surface never writes to or
 * replaces the installation's calendar data.
 */
export type OverviewPreview = {
  dashboard: Dashboard
  rules: RuleSummary[]
  recentChanges: RecentChange[]
  endpoints: (rule: Pick<RuleSummary, "source" | "destination">) => RuleEndpoints
}

const DANIEL_ACCOUNT: ConnectedAccount = {
  id: "preview-daniel",
  display_name: "Daniel Calatayud",
  email: "daniel@example.test",
  avatar_url: "/avatars/sam-work.png",
  state: "connected",
  rule_count: 1,
  authorized_at: "2026-09-27T09:00:00.000Z",
}

const PERSONAL_ACCOUNT: ConnectedAccount = {
  id: "preview-personal",
  display_name: "Daniel Personal",
  email: "personal@example.test",
  avatar_url: "/avatars/sam-personal.png",
  state: "connected",
  rule_count: 1,
  authorized_at: "2026-09-27T09:05:00.000Z",
}

const ACCOUNTS = [DANIEL_ACCOUNT, PERSONAL_ACCOUNT]

const CALENDARS: Record<string, DiscoveredCalendar[]> = {
  [DANIEL_ACCOUNT.id]: [
    { id: "daniel@example.test", summary: "Daniel IOG Calendar", access_role: "owner", primary: true },
    { id: "preview-io-clone", summary: "IO Clone", access_role: "writer", primary: false },
  ],
  [PERSONAL_ACCOUNT.id]: [
    { id: "personal@example.test", summary: "Personal", access_role: "owner", primary: true },
  ],
}

const RULE_IDS = {
  work: "preview-rule-work",
  personal: "preview-rule-personal",
} as const

function atMinutesAgo(now: number, minutes: number): string {
  return new Date(now - minutes * 60_000).toISOString()
}

function atEventTime(now: number, hoursAgo: number): string {
  const event = new Date(now - hoursAgo * 3_600_000)
  event.setMinutes(0, 0, 0)
  return event.toISOString()
}

function successfulRun(completedAt: string): RunOutcome {
  return {
    completed_at: completedAt,
    succeeded: true,
    full_run: true,
    created: 0,
    updated: 0,
    deleted: 0,
    conflicts: 0,
    checked_mappings: 12,
    drift: 0,
    failure_kind: null,
    last_succeeded_at: completedAt,
  }
}

function previewRule(
  id: string,
  source: RuleSummary["source"],
  destination: RuleSummary["destination"],
  lastSync: RunOutcome,
): RuleSummary {
  return {
    id,
    source,
    destination,
    privacy_policy: "busy_only",
    sync_all_day_events: false,
    tentative_events: "skip",
    unanswered_invitations: "wait",
    state: "enabled",
    reprojection_required: false,
    last_sync: lastSync,
    latest_preview: {
      completed_at: lastSync.completed_at,
      eligible_events: 12,
      excluded_events: 3,
      recurring_series: 2,
      occurrence_changes: 0,
    },
    running: null,
  }
}

function recordedEvent(starts: string): NonNullable<AuditEntry["event"]> {
  const ends = new Date(Date.parse(starts) + 60 * 60_000).toISOString()
  return {
    title: "IO R&D seminar",
    all_day: false,
    starts,
    ends,
    recurring: false,
    cancelled: true,
    renamed_from: null,
    moved_from: null,
  }
}

function recentChange(id: number, ruleId: string, occurredAt: string, firstOccurredAt: string): RecentChange {
  return {
    entry: {
      id,
      run_id: `preview-run-${id}`,
      occurred_at: occurredAt,
      rule_id: ruleId,
      action: "delete",
      outcome: "changed",
      category: "changed",
      reason: "source_cancelled",
      detail: "",
      source_event_id: `preview-event-${id}`,
      destination_event_id: `preview-projection-${id}`,
      event: recordedEvent(atEventTime(Date.parse(occurredAt), 0)),
      repeated: false,
      changed_fields: null,
    },
    repeats: 1,
    first_occurred_at: firstOccurredAt,
  }
}

export function overviewPreview(now: number = Date.now()): OverviewPreview {
  const latestSync = atMinutesAgo(now, 2)
  const workRule = previewRule(
    RULE_IDS.work,
    { connected_account_id: DANIEL_ACCOUNT.id, calendar_id: "daniel@example.test", calendar_name: "Daniel IOG Calendar" },
    { connected_account_id: DANIEL_ACCOUNT.id, calendar_id: "preview-io-clone", calendar_name: "IO Clone" },
    successfulRun(latestSync),
  )
  const personalRule = previewRule(
    RULE_IDS.personal,
    { connected_account_id: PERSONAL_ACCOUNT.id, calendar_id: "personal@example.test", calendar_name: "Personal" },
    { connected_account_id: DANIEL_ACCOUNT.id, calendar_id: "daniel@example.test", calendar_name: "Daniel IOG Calendar" },
    successfulRun(atMinutesAgo(now, 7)),
  )
  const rules = [workRule, personalRule]
  const dashboard: Dashboard = {
    health: "healthy",
    connected_accounts: ACCOUNTS.length,
    disconnected_accounts: 0,
    sync_rules: rules.length,
    enabled_rules: rules.filter((rule) => rule.state === "enabled").length,
    stopped_rules: 0,
    open_incidents: 0,
    last_synced_at: latestSync,
    blocked_events: 0,
    blocked_entry_id: null,
    blocked_rule_id: null,
  }
  const recentChanges = [
    recentChange(102, RULE_IDS.work, atMinutesAgo(now, 22 * 60 + 8), atMinutesAgo(now, 22 * 60 + 8)),
    recentChange(101, RULE_IDS.work, atMinutesAgo(now, 22 * 60 + 22), atMinutesAgo(now, 22 * 60 + 22)),
  ]
  const endpoints = (rule: Pick<RuleSummary, "source" | "destination">): RuleEndpoints => {
    const side = (endpoint: RuleSummary["source"]) => {
      const account = ACCOUNTS.find((candidate) => candidate.id === endpoint.connected_account_id)
      const calendars = CALENDARS[endpoint.connected_account_id]
      return {
        account,
        calendars,
        name: calendars?.find((calendar) => calendar.id === endpoint.calendar_id)?.summary ?? endpoint.calendar_name ?? "Secondary calendar",
      }
    }
    return { source: side(rule.source), destination: side(rule.destination), disconnected: [] }
  }
  return { dashboard, rules, recentChanges, endpoints }
}
