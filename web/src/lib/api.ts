export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...init?.headers },
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null
    throw new ApiError(body?.detail ?? "The request could not be completed.", response.status)
  }
  if (response.status === 204) return undefined as T
  try {
    return (await response.json()) as T
  } catch (error) {
    // The request reached a server, so an unparseable body is a service failure, not a
    // connectivity one; a proxy fallback page is the usual cause.
    if (!(error instanceof SyntaxError)) throw error
    throw new ApiError("The service returned an unreadable response.", response.status)
  }
}

export type SetupStatus = { administrator_configured: boolean }
export type SessionStatus = { authenticated: boolean }
export type Dashboard = {
  health: "healthy" | "attention"
  connected_accounts: number
  disconnected_accounts: number
  sync_rules: number
  enabled_rules: number
  stopped_rules: number
  open_incidents: number
  last_synced_at: string | null
  /** Events of existing rules whose latest decision was a block; the newest one is named. */
  blocked_events: number
  blocked_entry_id: number | null
  blocked_rule_id: string | null
}
export type Rule = {
  id: string
  source: { connected_account_id: string; calendar_id: string }
  destination: { connected_account_id: string; calendar_id: string }
  privacy_policy: "busy_only" | "copy_details"
  sync_all_day_events: boolean
  tentative_events: TentativeEvents
  unanswered_invitations: UnansweredInvitations
  state: string
  reprojection_required: boolean
}
/** What a rule does with events its source calendar answered Maybe to. */
export type TentativeEvents = "sync" | "mark" | "skip"
/** What a rule does with invitations its source calendar has not answered yet. */
export type UnansweredInvitations = "wait" | "as_tentative"
export type ProjectionHandling = "delete" | "detach"
export type RemovalResult = { deleted: number; detached: number; conflicts: number }
export type RunOutcome = {
  completed_at: string
  succeeded: boolean
  full_run: boolean
  created: number
  updated: number
  deleted: number
  conflicts: number
  checked_mappings: number
  drift: number
  failure_kind: string | null
  last_succeeded_at?: string | null
}
export type PreviewSummary = {
  completed_at: string
  eligible_events: number
  excluded_events: number
  recurring_series: number
  occurrence_changes: number
}
/** Work the service is running for a rule right now; it survives a page reload. */
export type RunningWork = {
  kind: "preview" | "sync" | "reconciliation" | "removal"
  started_at: string
  handling: ProjectionHandling | null
  /** Projections a removal is handling, once it has counted them. */
  total: number | null
  done: number
}
export type RuleSummary = Rule & {
  last_sync: RunOutcome | null
  latest_preview: PreviewSummary | null
  running: RunningWork | null
}
/** One written event; an identical repair repeated among recent entries is counted on it. */
export type RecentChange = {
  entry: AuditEntry
  repeats: number
  first_occurred_at: string
}
export type RuleDetail = Rule & {
  initial_lookback_days: number
  mapping_count: number
  last_sync: RunOutcome | null
  last_reconciliation: RunOutcome | null
  latest_preview: PreviewSummary | null
  running: RunningWork | null
}
export type RulePolicyPayload = {
  privacy_policy: "busy_only" | "copy_details"
  sync_all_day_events: boolean
  tentative_events: TentativeEvents
  unanswered_invitations: UnansweredInvitations
}
export type RuleEndpointPayload = { connected_account_id: string; calendar_id: string }
export type GoogleConfiguration = { configured: boolean; redirect_uri: string | null }
export type ConnectedAccount = {
  id: string
  display_name: string
  email: string
  avatar_url: string | null
  state: string
  rule_count: number
  /** When the account was last connected or reauthorized; null while disconnected. */
  authorized_at: string | null
}
export type GoogleAccountAccess = {
  calendar_api: boolean
  calendar_list_access: boolean
  event_access: boolean
  calendars_visible: number
  writable_calendars: number
}
export type DiscoveredCalendar = {
  id: string
  summary: string
  access_role: string
  primary: boolean
}
export type RulePreview = {
  rule_id: string
  eligible_events: number
  excluded_events: number
  recurring_series: number
  occurrence_changes: number
  sample: {
    source_event_id: string
    projected_title: string
    all_day: boolean
    kind: "single" | "series" | "occurrence"
    planned_action: "create" | "update" | "delete" | "ignore" | "conflict"
  }[]
}
export type SyncResult = {
  rule_id: string
  created: number
  updated: number
  deleted: number
  ignored: number
  conflicts: number
  consistent?: boolean
  checked_mappings?: number
  /** Reconcile Now only: what still differs after its sync. Reported, never repaired. */
  drift?: { kind: string; detail: string }[]
  /** Reconcile Now only: blocks the check itself recorded, beside the sync's `conflicts`. */
  reconciliation_conflicts?: { reason: string; detail: string }[]
}
export type ActivityCategory = "changed" | "unchanged" | "skipped" | "blocked"
export type AuditEntry = {
  id: number
  run_id: string | null
  occurred_at: string
  rule_id: string
  action: string
  outcome: string
  category: ActivityCategory
  reason: string | null
  detail: string
  source_event_id: string | null
  destination_event_id: string | null
  /** The source event as its run recorded it; null for entries recorded before names were kept. */
  event: RecordedEvent | null
  /** A repair that redoes the same event's previous one, recorded by an earlier run. */
  repeated: boolean
  /** The source fields this entry's Source Change touched; null when it recorded none. */
  changed_fields: string[] | null
}
export type RecordedTime = { all_day: boolean; starts: string | null; ends: string | null }
export type FieldChange = {
  field: string
  before: string | null
  after: string | null
  before_time: RecordedTime | null
  after_time: RecordedTime | null
  added: string[]
  removed: string[]
}
/** What changed in an entry's source event; values other than titles are kept for 90 days. */
export type SourceChange = {
  fields: string[]
  values_available: boolean
  changes: FieldChange[]
}
export type RecordedEvent = {
  title: string
  all_day: boolean
  starts: string | null
  ends: string | null
  recurring: boolean
  cancelled: boolean
  renamed_from: string | null
  /** The time the previous entry recorded, when this entry saw the event move. */
  moved_from: { all_day: boolean; starts: string | null; ends: string | null } | null
}
export type ActivityFilters = {
  ruleId?: string
  categories?: ActivityCategory[]
  before?: number
  /** Matches recorded event titles, ignoring case. */
  query?: string
}
export type EventSnapshot = {
  found: boolean
  cancelled: boolean
  title: string
  all_day: boolean
  starts: string | null
  ends: string | null
  recurring: boolean
  web_link: string | null
}
export type ActivityEvent = { source: EventSnapshot; destination: EventSnapshot | null }
export type Incident = {
  id: string
  rule_id: string | null
  category: string
  state: "open" | "resolved"
  summary: string
  opened_at: string
  updated_at: string
  resolved_at: string | null
  /** Why a resolved incident resolved; null while open or when the reason was not recorded. */
  resolution: "sync_succeeded" | "blocks_cleared" | "rule_removed" | null
  /** The Connected Account whose failure opened or last refreshed it; null when not recorded. */
  account_id: string | null
}

export const ACTIVITY_PAGE_SIZE = 100

export const api = {
  setup: () => request<SetupStatus>("/api/v1/setup"),
  session: () => request<SessionStatus>("/api/v1/session"),
  createAdmin: (password: string) =>
    request<SessionStatus>("/api/v1/setup/admin", {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
  logIn: (password: string) =>
    request<SessionStatus>("/api/v1/session", {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
  logOut: () => request<void>("/api/v1/session", { method: "DELETE" }),
  dashboard: () => request<Dashboard>("/api/v1/dashboard"),
  rules: () => request<RuleSummary[]>("/api/v1/rules"),
  rule: (ruleId: string) => request<RuleDetail>(`/api/v1/rules/${encodeURIComponent(ruleId)}`),
  updateRulePolicy: (ruleId: string, payload: RulePolicyPayload) =>
    request<Rule>(`/api/v1/rules/${encodeURIComponent(ruleId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  removeRule: (ruleId: string, projections: ProjectionHandling) =>
    request<RemovalResult>(
      `/api/v1/rules/${encodeURIComponent(ruleId)}?projections=${projections}`,
      { method: "DELETE" },
    ),
  replaceRuleCalendars: (
    ruleId: string,
    payload: {
      source: RuleEndpointPayload
      destination: RuleEndpointPayload
      projections: ProjectionHandling
    },
  ) =>
    request<{ rule: Rule } & RemovalResult>(
      `/api/v1/rules/${encodeURIComponent(ruleId)}/replace`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  googleConfiguration: () =>
    request<GoogleConfiguration>("/api/v1/google/configuration"),
  accounts: () => request<ConnectedAccount[]>("/api/v1/accounts"),
  disconnectAccount: (accountId: string) =>
    request<ConnectedAccount>(`/api/v1/accounts/${encodeURIComponent(accountId)}/disconnect`, {
      method: "POST",
    }),
  deleteAccount: (accountId: string) =>
    request<void>(`/api/v1/accounts/${encodeURIComponent(accountId)}`, { method: "DELETE" }),
  verifyAccountAccess: (accountId: string) =>
    request<GoogleAccountAccess>(`/api/v1/accounts/${encodeURIComponent(accountId)}/verify`, {
      method: "POST",
    }),
  calendars: (accountId: string) =>
    request<DiscoveredCalendar[]>(`/api/v1/accounts/${encodeURIComponent(accountId)}/calendars`),
  createRule: (payload: {
    source: { connected_account_id: string; calendar_id: string }
    destination: { connected_account_id: string; calendar_id: string }
  } & RulePolicyPayload) =>
    request<Rule>("/api/v1/rules", { method: "POST", body: JSON.stringify(payload) }),
  previewRule: (ruleId: string) =>
    request<RulePreview>(`/api/v1/rules/${encodeURIComponent(ruleId)}/preview`, {
      method: "POST",
    }),
  enableRule: (ruleId: string) =>
    request<Rule>(`/api/v1/rules/${encodeURIComponent(ruleId)}/enable`, {
      method: "POST",
    }),
  pauseRule: (ruleId: string) =>
    request<Rule>(`/api/v1/rules/${encodeURIComponent(ruleId)}/pause`, {
      method: "POST",
    }),
  syncRule: (ruleId: string) =>
    request<SyncResult>(`/api/v1/rules/${encodeURIComponent(ruleId)}/sync`, {
      method: "POST",
    }),
  reconcileRule: (ruleId: string) =>
    request<SyncResult>(`/api/v1/rules/${encodeURIComponent(ruleId)}/reconcile`, {
      method: "POST",
    }),
  activity: ({ ruleId, categories, before, query }: ActivityFilters = {}) => {
    const params = new URLSearchParams({ limit: String(ACTIVITY_PAGE_SIZE) })
    if (ruleId) params.set("rule_id", ruleId)
    for (const category of categories ?? []) params.append("category", category)
    if (before) params.set("before", String(before))
    if (query?.trim()) params.set("q", query.trim())
    return request<AuditEntry[]>(`/api/v1/audit-entries?${params}`)
  },
  activityEntry: (entryId: number) => request<AuditEntry>(`/api/v1/audit-entries/${entryId}`),
  activityEvent: (entryId: number) =>
    request<ActivityEvent>(`/api/v1/audit-entries/${entryId}/event`),
  activityChanges: (entryId: number) =>
    request<SourceChange>(`/api/v1/audit-entries/${entryId}/changes`),
  incidents: () => request<Incident[]>("/api/v1/incidents"),
  recentChanges: (limit = 5) => request<RecentChange[]>(`/api/v1/recent-changes?limit=${limit}`),
}
