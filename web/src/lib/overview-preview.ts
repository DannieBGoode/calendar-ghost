import { ACTIVITY_PAGE_SIZE } from "./api"
import type {
  ActivityCategory,
  ActivityEvent,
  ActivityFilters,
  AuditEntry,
  ConnectedAccount,
  Dashboard,
  DiscoveredCalendar,
  Incident,
  RecentChange,
  RuleDetail,
  RuleSummary,
  RunOutcome,
  SourceChange,
  StorageUsage,
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

export const PREVIEW_RULE_IDS = RULE_IDS

export function previewAccounts(): ConnectedAccount[] {
  return ACCOUNTS
}

export function previewCalendars(accountId: string): DiscoveredCalendar[] {
  return CALENDARS[accountId] ?? []
}

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
  const latestSync = atMinutesAgo(now, 0)
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

type PreviewEntryOptions = {
  id: number
  ruleId: string
  category: ActivityCategory
  action: string
  outcome: string
  reason: string
  title: string
  hoursAgo: number
  recurring?: boolean
  cancelled?: boolean
  changedFields?: string[] | null
  detail?: string
}

function previewEntry(now: number, options: PreviewEntryOptions): AuditEntry {
  const starts = atEventTime(now, options.hoursAgo)
  const ends = new Date(Date.parse(starts) + 60 * 60_000).toISOString()
  return {
    id: options.id,
    run_id: `preview-run-${Math.floor(options.id / 10)}`,
    occurred_at: atMinutesAgo(now, options.hoursAgo * 60 + 8),
    rule_id: options.ruleId,
    action: options.action,
    outcome: options.outcome,
    category: options.category,
    reason: options.reason,
    detail: options.detail ?? "",
    source_event_id: `preview-source-${options.id}`,
    destination_event_id: `preview-projection-${options.id}`,
    event: {
      title: options.title,
      all_day: false,
      starts,
      ends,
      recurring: options.recurring ?? false,
      cancelled: options.cancelled ?? false,
      renamed_from: options.reason === "source_changed" ? "Planning session" : null,
      moved_from: options.reason === "source_changed"
        ? { all_day: false, starts: atEventTime(now, options.hoursAgo + 1), ends: atEventTime(now, options.hoursAgo) }
        : null,
    },
    repeated: false,
    changed_fields: options.changedFields ?? null,
  }
}

export function previewActivityEntries(now: number = Date.now(), filters: ActivityFilters = {}): AuditEntry[] {
  const entries = [
    previewEntry(now, {
      id: 206,
      ruleId: RULE_IDS.work,
      category: "changed",
      action: "create",
      outcome: "changed",
      reason: "source_created",
      title: "Design review",
      hoursAgo: 2,
    }),
    previewEntry(now, {
      id: 205,
      ruleId: RULE_IDS.work,
      category: "changed",
      action: "update",
      outcome: "changed",
      reason: "source_changed",
      title: "Quarterly planning",
      hoursAgo: 4,
      recurring: true,
      changedFields: ["title", "time"],
    }),
    previewEntry(now, {
      id: 204,
      ruleId: RULE_IDS.personal,
      category: "skipped",
      action: "ignore",
      outcome: "unchanged",
      reason: "tentative_excluded",
      title: "Yoga class",
      hoursAgo: 7,
    }),
    previewEntry(now, {
      id: 203,
      ruleId: RULE_IDS.work,
      category: "blocked",
      action: "conflict",
      outcome: "blocked",
      reason: "destination_ownership_inconsistent",
      title: "Client workshop",
      hoursAgo: 10,
    }),
    previewEntry(now, {
      id: 202,
      ruleId: RULE_IDS.work,
      category: "changed",
      action: "delete",
      outcome: "changed",
      reason: "source_cancelled",
      title: "IO R&D seminar",
      hoursAgo: 22,
      cancelled: true,
    }),
    previewEntry(now, {
      id: 201,
      ruleId: RULE_IDS.personal,
      category: "unchanged",
      action: "ignore",
      outcome: "unchanged",
      reason: "projection_current",
      title: "Team stand-up",
      hoursAgo: 26,
    }),
  ]
  return entries
    .filter((entry) => !filters.ruleId || entry.rule_id === filters.ruleId)
    .filter((entry) => !filters.categories || filters.categories.includes(entry.category))
    .filter((entry) => !filters.query || entry.event?.title.toLocaleLowerCase().includes(filters.query.trim().toLocaleLowerCase()))
    .filter((entry) => !filters.before || entry.id < filters.before)
    .sort((left, right) => right.id - left.id)
    .slice(0, ACTIVITY_PAGE_SIZE)
}

function previewSnapshot(entry: AuditEntry, found: boolean): ActivityEvent["source"] {
  const event = entry.event
  return {
    found,
    cancelled: event?.cancelled ?? false,
    title: event?.title ?? "",
    all_day: event?.all_day ?? false,
    starts: event?.starts ?? null,
    ends: event?.ends ?? null,
    recurring: event?.recurring ?? false,
    web_link: found ? "https://calendar.google.com/calendar/u/0/r" : null,
  }
}

export function previewActivityEvent(entryId: number, now: number = Date.now()): ActivityEvent {
  const entry = previewActivityEntries(now).find((item) => item.id === entryId)
  if (!entry) throw new Error("Preview activity entry not found")
  return {
    source: previewSnapshot(entry, true),
    destination: entry.action === "delete" ? previewSnapshot(entry, false) : previewSnapshot(entry, true),
  }
}

export function previewActivityChanges(entryId: number, now: number = Date.now()): SourceChange {
  const entry = previewActivityEntries(now).find((item) => item.id === entryId)
  return {
    fields: entry?.changed_fields ?? [],
    values_available: true,
    changes: [
      {
        field: "title",
        before: "Planning session",
        after: entry?.event?.title ?? "Updated event",
        before_time: null,
        after_time: null,
        added: [],
        removed: [],
      },
      {
        field: "time",
        before: "9:00 AM",
        after: "10:00 AM",
        before_time: { all_day: false, starts: atEventTime(now, 5), ends: atEventTime(now, 4) },
        after_time: { all_day: false, starts: atEventTime(now, 4), ends: atEventTime(now, 3) },
        added: [],
        removed: [],
      },
    ].filter((change) => entry?.changed_fields?.includes(change.field) ?? false),
  }
}

export function previewActivityEntry(entryId: number, now: number = Date.now()): AuditEntry {
  const entry = previewActivityEntries(now).find((item) => item.id === entryId)
  if (!entry) throw new Error("Preview activity entry not found")
  return entry
}

export function previewIncidents(now: number = Date.now()): Incident[] {
  return [
    {
      id: "preview-incident-1",
      rule_id: RULE_IDS.work,
      category: "destination_ownership_inconsistent",
      state: "open",
      summary: "A destination event is not marked as managed",
      opened_at: atMinutesAgo(now, 3 * 60),
      updated_at: atMinutesAgo(now, 20),
      resolved_at: null,
      resolution: null,
      account_id: DANIEL_ACCOUNT.id,
    },
    {
      id: "preview-incident-2",
      rule_id: RULE_IDS.personal,
      category: "authorization",
      state: "resolved",
      summary: "Google access was renewed",
      opened_at: atMinutesAgo(now, 3 * 24 * 60),
      updated_at: atMinutesAgo(now, 24 * 60),
      resolved_at: atMinutesAgo(now, 24 * 60),
      resolution: "sync_succeeded",
      account_id: PERSONAL_ACCOUNT.id,
    },
  ]
}

export function previewStorage(): StorageUsage {
  return {
    database: {
      bytes: 2_840_000,
      reclaimable_bytes: 1_120_000,
      activity_entries: 248,
      oldest_activity_at: "2026-07-05T08:00:00.000Z",
    },
    logs: {
      bytes: 720_000,
      files: 3,
      oldest_at: "2026-09-29T08:00:00.000Z",
      newest_at: "2026-10-03T09:59:00.000Z",
    },
    activity_ages: [30, 60, 90, 180, 365],
  }
}

export function previewRuleDetail(ruleId: string, now: number = Date.now()): RuleDetail | null {
  const preview = overviewPreview(now)
  const rule = preview.rules.find((candidate) => candidate.id === ruleId)
  if (!rule) return null
  return {
    ...rule,
    initial_lookback_days: 30,
    mapping_count: 24,
    last_reconciliation: successfulRun(atMinutesAgo(now, 3)),
  }
}
