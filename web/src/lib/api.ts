import type { components } from "@/lib/api-schema"

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

/** Response and request bodies, generated from the backend's OpenAPI schema (web/openapi.json). */
type Schemas = components["schemas"]

export type SetupStatus = Schemas["SetupStatusResponse"]
export type SessionStatus = Schemas["SessionResponse"]
/** `blocked_events` counts events of existing rules whose latest decision was a block. */
export type Dashboard = Schemas["DashboardResponse"]
/** A rule's calendar with the name Google last gave it; null until Google lists it. */
export type RuleCalendar = Schemas["NamedCalendarEndpointResponse"]
export type Rule = Schemas["RuleResponse"]
/** What a rule does with events its source calendar answered Maybe to. */
export type TentativeEvents = Rule["tentative_events"]
/** What a rule does with invitations its source calendar has not answered yet. */
export type UnansweredInvitations = Rule["unanswered_invitations"]
export type ProjectionHandling = Schemas["ReplaceRuleRequest"]["projections"]
export type RemovalResult = Schemas["RemovalResponse"]
export type RunOutcome = Schemas["RunOutcomeResponse"]
export type PreviewSummary = Schemas["PreviewSummaryResponse"]
/** Work the service is running for a rule right now; it survives a page reload. */
export type RunningWork = Schemas["RuleWorkResponse"]
export type RuleSummary = Schemas["RuleSummaryResponse"]
/** One written event; an identical repair repeated among recent entries is counted on it. */
export type RecentChange = Schemas["RecentChangeResponse"]
export type RuleDetail = Schemas["RuleDetailResponse"]
export type RulePolicyPayload = Schemas["UpdateRulePolicyRequest"]
export type RuleEndpointPayload = Schemas["CalendarEndpointPayload"]
export type GoogleConfiguration = Schemas["GoogleConfigurationResponse"]
export type ConnectedAccount = Schemas["ConnectedAccountResponse"]
export type GoogleAccountAccess = Schemas["GoogleAccountAccessResponse"]
export type DiscoveredCalendar = Schemas["DiscoveredCalendarResponse"]
export type RulePreview = Schemas["RulePreviewResponse"]
export type SyncResult = Schemas["SyncResultResponse"]
/** Reconcile Now's sync, plus what still differs after it (reported, never repaired) and the
 * blocks the check itself recorded, beside the sync's `conflicts`. */
export type ReconcileResult = Schemas["ReconcileResultResponse"]
export type AuditEntry = Schemas["AuditEntryResponse"]
export type ActivityCategory = AuditEntry["category"]
export type RecordedTime = Schemas["RecordedTimeResponse"]
export type FieldChange = Schemas["FieldChangeResponse"]
/** What changed in an entry's source event; values other than titles are kept for 90 days. */
export type SourceChange = Schemas["SourceChangeResponse"]
export type RecordedEvent = Schemas["RecordedEventResponse"]
export type ActivityFilters = {
  ruleId?: string | undefined
  categories?: ActivityCategory[] | undefined
  before?: number | undefined
  /** Matches recorded event titles, ignoring case. */
  query?: string | undefined
}
export type EventSnapshot = Schemas["EventSnapshotResponse"]
export type ActivityEvent = Schemas["ActivityEventResponse"]
export type Incident = Schemas["IncidentResponse"]

export type DatabaseUsage = Schemas["DatabaseUsageResponse"]
export type LogUsage = Schemas["LogUsageResponse"]
export type StorageUsage = Schemas["StorageResponse"]
export type ClearableActivity = Schemas["ClearableActivityResponse"]
export type ClearedActivity = Schemas["ClearedActivityResponse"]
export const STORAGE_LOGS_URL = "/api/v1/storage/logs"

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
    request<Schemas["RuleReplacementResponse"]>(
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
  createRule: (payload: Schemas["CreateRuleRequest"]) =>
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
    request<ReconcileResult>(`/api/v1/rules/${encodeURIComponent(ruleId)}/reconcile`, {
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
  storage: () => request<StorageUsage>("/api/v1/storage"),
  clearableActivity: (days: number) =>
    request<ClearableActivity>(`/api/v1/storage/activity?older_than_days=${days}`),
  clearActivity: (days: number) =>
    request<ClearedActivity>("/api/v1/storage/activity/clear", {
      method: "POST",
      body: JSON.stringify({ older_than_days: days }),
    }),
  purgeLogs: () => request<void>(STORAGE_LOGS_URL, { method: "DELETE" }),
}
