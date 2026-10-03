import type { components, paths } from "@/lib/api-schema"

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json")
  const response = await fetch(path, { ...init, credentials: "same-origin", headers })
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    throw new ApiError(errorDetail(body) ?? "The request could not be completed.", response.status)
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

/**
 * The message in an error body: a route's own `detail` string, or the messages of FastAPI's
 * request validation errors, whose `detail` is a list.
 */
export function errorDetail(body: unknown): string | null {
  if (typeof body !== "object" || body === null || !("detail" in body)) return null
  const { detail } = body
  if (typeof detail === "string") return detail
  if (!Array.isArray(detail)) return null
  const messages = detail.flatMap((item: unknown) =>
    typeof item === "object" && item !== null && "msg" in item && typeof item.msg === "string" ? [item.msg] : [],
  )
  return messages.length ? messages.join("; ") : null
}

type Method = "get" | "post" | "patch" | "delete"
/** The methods a path declares in the schema. */
type MethodOf<P extends keyof paths> = {
  [M in Method]: paths[P][M] extends { responses: unknown } ? M : never
}[Method]
type JsonContent<R> = R extends { content: { "application/json": infer B } } ? B : undefined
/** The body of a route's success response; undefined for 204 No Content. */
type Success<P extends keyof paths, M extends MethodOf<P>> =
  paths[P][M] extends { responses: infer R } ? JsonContent<R[Extract<keyof R, 200 | 201 | 204>]> : never
type Payload<P extends keyof paths, M extends MethodOf<P>> =
  paths[P][M] extends { requestBody: { content: { "application/json": infer B } } } ? B : never
type CallOptions<P extends keyof paths, M extends MethodOf<P>> = {
  /** Values for the path's `{name}` placeholders. */
  params?: Record<string, string | number>
  query?: URLSearchParams
  body?: Payload<P, M>
}

/**
 * Calls one route. Its path template and method select the request and response types from the
 * generated schema, so a call cannot name one route and expect another route's body.
 */
function call<P extends keyof paths, M extends MethodOf<P>>(
  path: P,
  method: M,
  { params = {}, query, body }: CallOptions<P, M> = {},
): Promise<Success<P, M>> {
  const filled = path.replace(/\{(\w+)\}/g, (_, name: string) => {
    const value = params[name]
    if (value === undefined) throw new Error(`Missing path parameter ${name} for ${path}`)
    return encodeURIComponent(String(value))
  })
  const url = query?.size ? `${filled}?${query}` : filled
  return request<Success<P, M>>(url, {
    method: method.toUpperCase(),
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })
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
  setup: () => call("/api/v1/setup", "get"),
  session: () => call("/api/v1/session", "get"),
  createAdmin: (password: string) => call("/api/v1/setup/admin", "post", { body: { password } }),
  logIn: (password: string) => call("/api/v1/session", "post", { body: { password } }),
  logOut: () => call("/api/v1/session", "delete"),
  dashboard: () => call("/api/v1/dashboard", "get"),
  rules: () => call("/api/v1/rules", "get"),
  rule: (ruleId: string) => call("/api/v1/rules/{rule_id}", "get", { params: { rule_id: ruleId } }),
  updateRulePolicy: (ruleId: string, payload: RulePolicyPayload) =>
    call("/api/v1/rules/{rule_id}", "patch", { params: { rule_id: ruleId }, body: payload }),
  removeRule: (ruleId: string, projections: ProjectionHandling) =>
    call("/api/v1/rules/{rule_id}", "delete", {
      params: { rule_id: ruleId },
      query: new URLSearchParams({ projections }),
    }),
  replaceRuleCalendars: (ruleId: string, payload: Schemas["ReplaceRuleRequest"]) =>
    call("/api/v1/rules/{rule_id}/replace", "post", { params: { rule_id: ruleId }, body: payload }),
  googleConfiguration: () => call("/api/v1/google/configuration", "get"),
  accounts: () => call("/api/v1/accounts", "get"),
  disconnectAccount: (accountId: string) =>
    call("/api/v1/accounts/{account_id}/disconnect", "post", { params: { account_id: accountId } }),
  deleteAccount: (accountId: string) =>
    call("/api/v1/accounts/{account_id}", "delete", { params: { account_id: accountId } }),
  verifyAccountAccess: (accountId: string) =>
    call("/api/v1/accounts/{account_id}/verify", "post", { params: { account_id: accountId } }),
  calendars: (accountId: string) =>
    call("/api/v1/accounts/{account_id}/calendars", "get", { params: { account_id: accountId } }),
  createRule: (payload: Schemas["CreateRuleRequest"]) => call("/api/v1/rules", "post", { body: payload }),
  previewRule: (ruleId: string) =>
    call("/api/v1/rules/{rule_id}/preview", "post", { params: { rule_id: ruleId } }),
  enableRule: (ruleId: string) => call("/api/v1/rules/{rule_id}/enable", "post", { params: { rule_id: ruleId } }),
  pauseRule: (ruleId: string) => call("/api/v1/rules/{rule_id}/pause", "post", { params: { rule_id: ruleId } }),
  syncRule: (ruleId: string) => call("/api/v1/rules/{rule_id}/sync", "post", { params: { rule_id: ruleId } }),
  reconcileRule: (ruleId: string) =>
    call("/api/v1/rules/{rule_id}/reconcile", "post", { params: { rule_id: ruleId } }),
  activity: ({ ruleId, categories, before, query }: ActivityFilters = {}) => {
    const params = new URLSearchParams({ limit: String(ACTIVITY_PAGE_SIZE) })
    if (ruleId) params.set("rule_id", ruleId)
    for (const category of categories ?? []) params.append("category", category)
    if (before) params.set("before", String(before))
    if (query?.trim()) params.set("q", query.trim())
    return call("/api/v1/audit-entries", "get", { query: params })
  },
  activityEntry: (entryId: number) =>
    call("/api/v1/audit-entries/{entry_id}", "get", { params: { entry_id: entryId } }),
  activityEvent: (entryId: number) =>
    call("/api/v1/audit-entries/{entry_id}/event", "get", { params: { entry_id: entryId } }),
  activityChanges: (entryId: number) =>
    call("/api/v1/audit-entries/{entry_id}/changes", "get", { params: { entry_id: entryId } }),
  incidents: () => call("/api/v1/incidents", "get"),
  recentChanges: (limit = 5) =>
    call("/api/v1/recent-changes", "get", { query: new URLSearchParams({ limit: String(limit) }) }),
  storage: () => call("/api/v1/storage", "get"),
  clearableActivity: (days: number) =>
    call("/api/v1/storage/activity", "get", { query: new URLSearchParams({ older_than_days: String(days) }) }),
  clearActivity: (days: number) =>
    call("/api/v1/storage/activity/clear", "post", { body: { older_than_days: days } }),
  purgeLogs: () => call(STORAGE_LOGS_URL, "delete"),
}
