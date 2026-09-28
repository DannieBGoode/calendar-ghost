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
  sync_rules: number
  open_incidents: number
}
export type Rule = {
  id: string
  source: { connected_account_id: string; calendar_id: string }
  destination: { connected_account_id: string; calendar_id: string }
  privacy_policy: "busy_only" | "copy_details"
  sync_all_day_events: boolean
  state: string
}
export type GoogleConfiguration = { configured: boolean; redirect_uri: string | null }
export type ConnectedAccount = {
  id: string
  display_name: string
  email: string
  state: string
  rule_count: number
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
  sample: { source_event_id: string; projected_title: string; all_day: boolean }[]
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
  drift?: { kind: string; detail: string }[]
}
export type AuditEntry = {
  occurred_at: string
  rule_id: string
  action: string
  outcome: string
  detail: string
}
export type Incident = {
  id: string
  rule_id: string | null
  category: string
  state: "open" | "resolved"
  summary: string
  opened_at: string
  updated_at: string
}

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
  rules: () => request<Rule[]>("/api/v1/rules"),
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
    privacy_policy: "busy_only" | "copy_details"
    sync_all_day_events: boolean
  }) =>
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
  activity: () => request<AuditEntry[]>("/api/v1/audit-entries"),
  incidents: () => request<Incident[]>("/api/v1/incidents"),
}
