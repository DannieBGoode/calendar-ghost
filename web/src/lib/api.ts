import type { components, paths } from "@/lib/api-schema"

/** An error body's parameters; the Web UI fills its translated message with them. */
export type ApiErrorParams = Readonly<Record<string, string | number | null>>
/** What an error body says besides its detail: a stable code (ADR 0026) and its parameters. */
export type ApiErrorCode = { code?: string | null; params?: ApiErrorParams }

export class ApiError extends Error {
  /** The server's stable error code; null when the body had none. */
  public readonly code: string | null
  public readonly params: ApiErrorParams

  constructor(
    message: string,
    public readonly status: number,
    /** The server's English detail, including validation messages; null when it sent none. */
    public readonly detail: string | null = null,
    { code = null, params = {} }: ApiErrorCode = {},
  ) {
    super(message)
    this.code = code
    this.params = params
  }
}

/** The server answered, but its body was not JSON; a proxy fallback page is the usual cause. */
export class UnreadableResponseError extends ApiError {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json")
  const response = await fetch(path, { ...init, credentials: "same-origin", headers })
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    const detail = errorDetail(body)
    throw new ApiError(detail ?? "The request could not be completed.", response.status, detail, errorCode(body))
  }
  if (response.status === 204) return undefined as T
  try {
    return (await response.json()) as T
  } catch (error) {
    // The request reached a server, so an unparseable body is a service failure, not a
    // connectivity one; a proxy fallback page is the usual cause.
    if (!(error instanceof SyntaxError)) throw error
    throw new UnreadableResponseError("The service returned an unreadable response.", response.status)
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

/** The stable code and parameters of an error body; params keep only text, numbers, and null. */
function errorCode(body: unknown): ApiErrorCode {
  if (typeof body !== "object" || body === null) return { code: null, params: {} }
  const code = "code" in body && typeof body.code === "string" ? body.code : null
  const raw = "params" in body ? body.params : null
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return { code, params: {} }
  const params = Object.fromEntries(
    Object.entries(raw).filter(
      (entry): entry is [string, string | number | null] =>
        entry[1] === null || typeof entry[1] === "string" || typeof entry[1] === "number",
    ),
  )
  return { code, params }
}

type Method = "get" | "post" | "put" | "patch" | "delete"
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
  // Widened before it is read: the inputs' own type spans every route, which is too wide to narrow.
  const given: unknown = inputs
  const { params, query, body } = (given ?? {}) as {
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

/**
 * `status` is the server's verdict; the Overview never derives its own (ADR 0024). `problems`
 * lists every current problem, most urgent first, and `blocked_events` counts events of existing
 * rules whose latest decision was a block.
 */
export type Dashboard = Schemas["DashboardResponse"]
export type InstallationHealth = Dashboard["status"]
export type ServerProblem = Schemas["ProblemResponse"]
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
export type ConnectedAccount = Schemas["ConnectedAccountResponse"]
export type DiscoveredCalendar = Schemas["DiscoveredCalendarResponse"]
export type RulePreview = Schemas["RulePreviewResponse"]
export type SyncResult = Schemas["SyncResultResponse"]
/** Reconcile Now's sync, plus what still differs after it (reported, never repaired) and the
 * blocks the check itself recorded, beside the sync's `conflicts`. */
export type ReconcileResult = Schemas["ReconcileResultResponse"]
export type AuditEntry = Schemas["AuditEntryResponse"]
export type ActivityCategory = AuditEntry["category"]
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
export type Incident = Schemas["IncidentResponse"]

export type DatabaseUsage = Schemas["DatabaseUsageResponse"]
export type LogUsage = Schemas["LogUsageResponse"]
export const STORAGE_LOGS_URL = "/api/v1/storage/logs"

export type SetupStatus = Schemas["SetupStatusResponse"]
export type SessionStatus = Schemas["SessionResponse"]
export type SignedInUser = Schemas["SignedInUserResponse"]

export type IntegrationToken = Schemas["IntegrationTokenResponse"]
export type IssuedIntegrationToken = Schemas["IssuedIntegrationTokenResponse"]
/** What a token may read: its User's Installation Status, and for an administrator's, Installation Health. */
export type IntegrationScope = IntegrationToken["scopes"][number]

/** Who may become a User: Only Me, the default, or Invitation Only. */
export type Registration = Schemas["RegistrationResponse"]
export type RegistrationPolicy = Registration["policy"]
/** A User as an Installation Administrator sees them: never their calendars, rules, or events. */
export type Person = Schemas["UserResponse"]
export type PersonRole = Person["role"]
export type PersonState = Person["state"]
/** A row of People: the person, their Installation Status verdict, and their resource use. */
export type PersonRow = Schemas["PersonResponse"]
/** The whole installation's verdict, and how many Users are in each; it names nobody. */
export type InstallationHealthReport = Schemas["InstallationHealthResponse"]
export type InstallationHint = Schemas["InstallationHintResponse"]
/** An Installation Status verdict, as People filters and sorts by it. */
export type Verdict = PersonRow["verdict"]
/** How much one User uses: counts only, never what their records say. */
export type ResourceUse = Schemas["ResourceUseResponse"]
/**
 * What the Operator Overview shows about one User, to an administrator and to that User: their
 * Installation Status with calendars only as "Calendar 1", "Calendar 2", and their resource use.
 */
export type UserOverview = Schemas["UserOverviewResponse"]
/** One page of the people an administrator looks for, and how many match across every page. */
export type PeoplePage = Schemas["UserPageResponse"]
type PeopleParams = NonNullable<paths["/api/v1/users"]["get"]["parameters"]["query"]>
export type PeopleSort = NonNullable<PeopleParams["sort"]>
export type SortOrder = NonNullable<PeopleParams["order"]>
/** What the People page asks for; an empty role, state, or verdict matches everyone. */
export type PeopleQuery = {
  /** Part of an email, in any case. */
  search: string
  role: PersonRole | ""
  state: PersonState | ""
  verdict: Verdict | ""
  sort: PeopleSort
  order: SortOrder
  /** From 1. */
  page: number
}
export type PendingInvitation = Schemas["PendingInvitationResponse"]
/** An Invitation or Password Reset Link; its token is shown once. */
export type IssuedLink = Schemas["IssuedLinkResponse"]
export type UserDeletion = Schemas["UserDeletionResponse"]

export const ACTIVITY_PAGE_SIZE = 100
export const PEOPLE_PAGE_SIZE = 50

export const api = {
  setup: () => call("/api/v1/setup", "get"),
  session: () => call("/api/v1/session", "get"),
  createAdmin: (email: string, password: string) =>
    call("/api/v1/setup/admin", "post", { body: { email, password } }),
  /** A null email signs in the upgraded first User, until they add one. */
  logIn: (email: string | null, password: string) =>
    call("/api/v1/session", "post", { body: { email, password } }),
  /** Adds the email the upgraded first User must add; changing one also needs the password. */
  setOwnEmail: (email: string, password?: string) =>
    call("/api/v1/account/email", "put", { body: password === undefined ? { email } : { email, password } }),
  logOut: () => call("/api/v1/session", "delete"),
  /** Ends every other session of the signed-in User. */
  changeOwnPassword: (currentPassword: string, newPassword: string) =>
    call("/api/v1/account/password", "put", {
      body: { current_password: currentPassword, new_password: newPassword },
    }),
  setIncidentEmails: (notifyByEmail: boolean) =>
    call("/api/v1/account/notifications", "put", { body: { notify_by_email: notifyByEmail } }),
  /** What the Operator Overview shows administrators about the signed-in User. */
  /** Whether the signed-in User may delete themself now, and whether nobody would remain. */
  ownAccountDeletion: () => call("/api/v1/account/deletion", "get"),
  deleteOwnAccount: (password: string, projections: ProjectionHandling) =>
    call("/api/v1/account", "delete", { body: { password, projections } }),
  registration: () => call("/api/v1/registration", "get"),
  setRegistrationPolicy: (policy: RegistrationPolicy) => call("/api/v1/registration", "put", { body: { policy } }),
  invitations: () => call("/api/v1/invitations", "get"),
  invite: () => call("/api/v1/invitations", "post"),
  revokeInvitation: (invitationId: string) =>
    call("/api/v1/invitations/{invitation_id}", "delete", { params: { invitation_id: invitationId } }),
  checkInvitation: (token: string) => call("/api/v1/invitations/check", "post", { body: { token } }),
  /** Creates the invited User and signs them in. */
  acceptInvitation: (token: string, email: string, password: string) =>
    call("/api/v1/invitations/accept", "post", { body: { token, email, password } }),
  checkPasswordReset: (token: string) => call("/api/v1/password-resets/check", "post", { body: { token } }),
  resetPassword: (token: string, password: string) =>
    call("/api/v1/password-resets", "post", { body: { token, password } }),
  people: ({ search, role, state, verdict, sort, order, page }: PeopleQuery) =>
    call("/api/v1/users", "get", {
      query: {
        ...(search.trim() ? { search: search.trim() } : {}),
        role: role || null,
        state: state || null,
        verdict: verdict || null,
        sort,
        order,
        page,
        page_size: PEOPLE_PAGE_SIZE,
      },
    }),
  setPersonRole: (userId: string, role: PersonRole) =>
    call("/api/v1/users/{user_id}/role", "put", { params: { user_id: userId }, body: { role } }),
  setPersonState: (userId: string, state: PersonState) =>
    call("/api/v1/users/{user_id}/state", "put", { params: { user_id: userId }, body: { state } }),
  issuePasswordResetLink: (userId: string) =>
    call("/api/v1/users/{user_id}/password-reset-links", "post", { params: { user_id: userId } }),
  deletePerson: (userId: string) => call("/api/v1/users/{user_id}", "delete", { params: { user_id: userId } }),
  /** What the Operator Overview shows about one person; 404 for anyone but an administrator. */
  personOverview: (userId: string) =>
    call("/api/v1/users/{user_id}/overview", "get", { params: { user_id: userId } }),
  /** Every User's verdict counted, and incidents about the installation itself; names nobody. */
  installationHealth: () => call("/api/v1/installation/health", "get"),
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
  integrationTokens: () => call("/api/v1/integration-tokens", "get"),
  issueIntegrationToken: (name: string, scopes: IntegrationScope[] = ["status:read"]) =>
    call("/api/v1/integration-tokens", "post", { body: { name, scopes } }),
  revokeIntegrationToken: (id: string) =>
    call("/api/v1/integration-tokens/{token_id}", "delete", { params: { token_id: id } }),
}
