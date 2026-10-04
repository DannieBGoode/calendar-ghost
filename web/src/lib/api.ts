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
type Operation<P extends keyof paths, M extends MethodOf<P>> = paths[P][M]
type JsonContent<R> = R extends { content: { "application/json": infer B } } ? B : undefined
/** The body of a route's success response; undefined for 204 No Content. */
type Success<O> = O extends { responses: infer R } ? JsonContent<R[Extract<keyof R, 200 | 201 | 204>]> : never
type QueryValue = string | number | boolean | readonly (string | number)[] | null | undefined

/**
 * What a route takes besides its path and method. Each part is required exactly when the schema
 * requires it, and absent when the route declares none.
 */
type Inputs<O> = (O extends { parameters: { path: infer Path } } ? { params: Path } : { params?: never }) &
  (O extends { parameters: { query: infer Query } }
    ? { query: Query }
    : O extends { parameters: { query?: infer Query } }
      ? [Query] extends [undefined]
        ? { query?: never }
        : { query?: Query }
      : { query?: never }) &
  (O extends { requestBody: { content: { "application/json": infer Body } } } ? { body: Body } : { body?: never })
/** The inputs argument, optional only when the route requires none. */
type InputArgs<O> = Record<never, never> extends Inputs<O> ? [inputs?: Inputs<O>] : [inputs: Inputs<O>]

function queryString(query: Readonly<Record<string, QueryValue>>): string {
  const search = new URLSearchParams()
  for (const [name, value] of Object.entries(query)) {
    if (value === null || value === undefined) continue
    if (Array.isArray(value)) for (const item of value) search.append(name, String(item))
    else search.set(name, String(value))
  }
  return search.size ? `?${search}` : ""
}

/**
 * Calls one route. Its path template and method select every type from the generated schema:
 * the path values, query, and body it requires, and the body it returns. A call cannot name one
 * route and expect another route's body, or leave out an input the route requires.
 */
/** Exported for the type tests in api.test.ts; app code calls `api`. */
export function call<P extends keyof paths, M extends MethodOf<P>>(
  path: P,
  method: M,
  ...[inputs]: InputArgs<Operation<P, M>>
): Promise<Success<Operation<P, M>>> {
  const { params, query, body } = (inputs ?? {}) as {
    params?: Readonly<Record<string, string | number>>
    query?: Readonly<Record<string, QueryValue>>
    body?: unknown
  }
  const filled = path.replace(/\{(\w+)\}/g, (_, name: string) => {
    const value = params?.[name]
    if (value === undefined) throw new Error(`Missing path parameter ${name} for ${path}`)
    return encodeURIComponent(String(value))
  })
  return request<Success<Operation<P, M>>>(`${filled}${query ? queryString(query) : ""}`, {
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
      query: { projections },
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
  activity: ({ ruleId, categories, before, query }: ActivityFilters = {}) =>
    call("/api/v1/audit-entries", "get", {
      query: {
        limit: ACTIVITY_PAGE_SIZE,
        rule_id: ruleId || null,
        category: categories ?? null,
        before: before ?? null,
        q: query?.trim() || null,
      },
    }),
  activityEntry: (entryId: number) =>
    call("/api/v1/audit-entries/{entry_id}", "get", { params: { entry_id: entryId } }),
  activityEvent: (entryId: number) =>
    call("/api/v1/audit-entries/{entry_id}/event", "get", { params: { entry_id: entryId } }),
  activityChanges: (entryId: number) =>
    call("/api/v1/audit-entries/{entry_id}/changes", "get", { params: { entry_id: entryId } }),
  incidents: () => call("/api/v1/incidents", "get"),
  recentChanges: (limit = 5) =>
    call("/api/v1/recent-changes", "get", { query: { limit } }),
  storage: () => call("/api/v1/storage", "get"),
  clearableActivity: (days: number) =>
    call("/api/v1/storage/activity", "get", { query: { older_than_days: days } }),
  clearActivity: (days: number) =>
    call("/api/v1/storage/activity/clear", "post", { body: { older_than_days: days } }),
  purgeLogs: () => call(STORAGE_LOGS_URL, "delete"),
}
