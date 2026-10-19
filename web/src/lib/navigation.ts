export type AppView = "overview" | "rules" | "activity" | "people" | "settings"
/** The Settings tabs, in order; Administration is for Installation Administrators only. */
export const SETTINGS_TABS = ["account", "connections", "administration"] as const
export type SettingsTab = (typeof SETTINGS_TABS)[number]
/** The tab Settings opens at unless Google's return or an account link calls for Connections. */
export const DEFAULT_SETTINGS_TAB: SettingsTab = "account"
/**
 * What a provider's return, or a link to one Connected Account, carries in the address; `limit` is
 * the plan's account limit a new account met.
 */
export const SETTINGS_ARRIVAL_PARAMS = ["oauth", "provider", "account", "resumed", "limit"] as const

/**
 * The tab Settings without one shows: Connections when a provider returned or an account is named,
 * as the OAuth callback and older links open it, and Your account otherwise.
 */
export function defaultSettingsTab(search: string): SettingsTab {
  const params = new URLSearchParams(search)
  return SETTINGS_ARRIVAL_PARAMS.some((name) => params.has(name)) ? "connections" : DEFAULT_SETTINGS_TAB
}

/** People's tabs: everyone here, then the Invitations still waiting, then the Plans that limit them. */
export type PeopleTab = "everyone" | "invitations" | "plans"
export const DEFAULT_PEOPLE_TAB: PeopleTab = "everyone"

/** A Plan's side panel shows its Limits, the editor, or its People, who has it and who could. */
export type PlanPanelTab = "limits" | "people"
/** The side panel open beside the Plans catalog: one Plan's, by key, or a new Plan's with null. */
export type PlanPanel = { plan: string | null; tab: PlanPanelTab }

/** Activity's tabs: what the rules did, then the Incidents that needed or need attention. */
export type ActivityTab = "history" | "incidents"
export const DEFAULT_ACTIVITY_TAB: ActivityTab = "history"

export type AppLocation = {
  view: AppView
  ruleId: string | null
  /** The rule's preview page, under its details. */
  rulePreview?: boolean
  settingsTab?: SettingsTab
  /** One person's page under People. */
  personId?: string
  /** The Invitations or Plans tab of People; People opens at everyone here. */
  peopleTab?: PeopleTab
  /** The side panel open beside the Plans tab's catalog. */
  planPanel?: PlanPanel
  /** The Incidents tab of Activity; Activity opens at its history. */
  activityTab?: ActivityTab
  /** One Incident, open beside the Incidents table. */
  incidentId?: string
}
/**
 * Changes view. A notice is announced on arrival; `createRule` opens the rule builder; `search`
 * carries filters such as `?rule=` into the destination.
 */
export type ViewOptions = {
  notice?: string
  /** An attention notice stays until dismissed and offers a way to review what happened. */
  noticeTone?: "attention" | undefined
  createRule?: boolean
  /** Moves focus to the Plan panel the address opens, as opening it from the Plans tab does. */
  planPanelFocus?: boolean
  search?: string
  /** The Settings tab to open, such as Connections for a link about Google accounts. */
  settingsTab?: SettingsTab
}
export type ViewChange = (view: AppView, options?: ViewOptions) => void
export type OpenRule = (ruleId: string, options?: ViewOptions) => void
/** Opens a rule's preview page, which previews the rule as it opens. */
export type OpenRulePreview = (ruleId: string) => void
export type OpenSettingsTab = (tab: SettingsTab) => void
export type OpenPerson = (personId: string) => void
/** Opens a Plan's side panel on People's Plans tab from anywhere, as a new arrival there. */
export type OpenPlan = (panel: PlanPanel) => void

export function activitySearch(ruleId: string): string {
  return `?rule=${encodeURIComponent(ruleId)}`
}

/** Settings, opened at one Connected Account's row, such as the one a stopped rule needs. */
export function accountSearch(accountId: string): string {
  return `?account=${encodeURIComponent(accountId)}`
}

/** Settings → Connections, where Google accounts are connected and reauthorized. */
export function connectionsPath(search = ""): string {
  return `${appPathForSettingsTab("connections")}${search}`
}

const APP_VIEW_PATHS: Record<AppView, string> = {
  overview: "/overview",
  rules: "/rules",
  activity: "/activity",
  people: "/people",
  settings: "/settings",
}

const PATH_VIEWS = new Map(
  Object.entries(APP_VIEW_PATHS).map(([view, path]) => [path, view as AppView]),
)
const RULE_PATH = /^\/rules\/([^/]+)$/
const RULE_PREVIEW_PATH = /^\/rules\/([^/]+)\/preview$/
const PERSON_PATH = /^\/people\/([^/]+)$/
/** Each People tab's address; one of these is never a person's page. */
const PEOPLE_TAB_PATHS: Record<PeopleTab, string> = {
  everyone: APP_VIEW_PATHS.people,
  invitations: "/people/invitations",
  plans: "/people/plans",
}
/** One Plan's panel, or with `new`, which no Plan's key can be, a new Plan's. */
const PLAN_PATH = /^\/people\/plans\/([^/]+)(\/people)?$/
const NEW_PLAN = "new"
/** The query naming the Plan a new one copies, as Duplicate opens it. */
const PLAN_COPY_PARAM = "copy"
const INCIDENTS_PATH = "/activity/incidents"
const INCIDENT_PATH = /^\/activity\/incidents\/([^/]+)$/
const SETTINGS_TAB_PATH = /^\/settings\/([^/]+)$/

function normalize(pathname: string): string {
  return pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname
}

/** An identifier from one segment of an address, or null when it is blank or not encoded right. */
function decodedSegment(encoded: string | undefined): string | null {
  if (encoded === undefined) return null
  try {
    const id = decodeURIComponent(encoded)
    return id.trim() ? id : null
  } catch {
    return null
  }
}

function idFromPath(pattern: RegExp, pathname: string): string | null {
  return decodedSegment(pattern.exec(pathname)?.[1])
}

function ruleIdFromPath(pathname: string): string | null {
  return idFromPath(RULE_PATH, pathname)
}

function peopleTabFromPath(pathname: string): PeopleTab | null {
  const tabs = Object.entries(PEOPLE_TAB_PATHS) as [PeopleTab, string][]
  return tabs.find(([tab, path]) => tab !== DEFAULT_PEOPLE_TAB && path === pathname)?.[0] ?? null
}

function planPanelFromPath(pathname: string): PlanPanel | null {
  const match = PLAN_PATH.exec(pathname)
  const plan = decodedSegment(match?.[1])
  if (!match || plan === null) return null
  if (plan === NEW_PLAN) return { plan: null, tab: "limits" }
  return { plan, tab: match[2] ? "people" : "limits" }
}

function settingsTabFromPath(pathname: string): SettingsTab | null {
  const segment = SETTINGS_TAB_PATH.exec(pathname)?.[1]
  return SETTINGS_TABS.find((tab) => tab === segment) ?? null
}

export function appLocationFromPathname(pathname: string): AppLocation {
  const normalized = normalize(pathname)
  const ruleId = ruleIdFromPath(normalized)
  if (ruleId !== null) return { view: "rules", ruleId }
  const previewedRuleId = idFromPath(RULE_PREVIEW_PATH, normalized)
  if (previewedRuleId !== null) return { view: "rules", ruleId: previewedRuleId, rulePreview: true }
  const peopleTab = peopleTabFromPath(normalized)
  if (peopleTab !== null) return { view: "people", ruleId: null, peopleTab }
  const planPanel = planPanelFromPath(normalized)
  if (planPanel !== null) return { view: "people", ruleId: null, peopleTab: "plans", planPanel }
  if (normalized === INCIDENTS_PATH) return { view: "activity", ruleId: null, activityTab: "incidents" }
  const incidentId = idFromPath(INCIDENT_PATH, normalized)
  if (incidentId !== null) return { view: "activity", ruleId: null, activityTab: "incidents", incidentId }
  const personId = idFromPath(PERSON_PATH, normalized)
  if (personId !== null) return { view: "people", ruleId: null, personId }
  const settingsTab = settingsTabFromPath(normalized)
  if (settingsTab !== null) return { view: "settings", ruleId: null, settingsTab }
  return { view: PATH_VIEWS.get(normalized) ?? "overview", ruleId: null }
}

/** A location with Settings' tab filled in: one the path does not name follows the query. */
export function withSettingsTab(location: AppLocation, search: string): AppLocation {
  if (location.view !== "settings" || location.settingsTab) return location
  return { ...location, settingsTab: defaultSettingsTab(search) }
}

/** Where an address opens, including the tab of Settings without one in its path. */
export function appLocationFromUrl(pathname: string, search: string): AppLocation {
  return withSettingsTab(appLocationFromPathname(pathname), search)
}

/** Whether the browser is showing this rule's details right now. */
export function isViewingRule(ruleId: string, pathname: string = window.location.pathname): boolean {
  return appLocationFromPathname(pathname).ruleId === ruleId
}

export function appPathForView(view: AppView): string {
  return APP_VIEW_PATHS[view]
}

export function appPathForRule(ruleId: string): string {
  return `${APP_VIEW_PATHS.rules}/${encodeURIComponent(ruleId)}`
}

export function appPathForRulePreview(ruleId: string): string {
  return `${appPathForRule(ruleId)}/preview`
}

export function appPathForPeopleTab(tab: PeopleTab): string {
  return PEOPLE_TAB_PATHS[tab]
}

/**
 * A Plan's panel: its Limits at `/people/plans/<key>`, its People under it, or New plan at
 * `/people/plans/new`, carrying the key of the Plan it copies, as Duplicate opens it.
 */
export function appPathForPlanPanel({ plan, tab }: PlanPanel, copyOf: string | null = null): string {
  const plans = PEOPLE_TAB_PATHS.plans
  if (plan === null) {
    const search = copyOf ? `?${new URLSearchParams({ [PLAN_COPY_PARAM]: copyOf }).toString()}` : ""
    return `${plans}/${NEW_PLAN}${search}`
  }
  const path = `${plans}/${encodeURIComponent(plan)}`
  return tab === "people" ? `${path}/people` : path
}

/** The key of the Plan a new Plan's panel copies, from its address's query; null for none. */
export function planCopyFromSearch(search: string): string | null {
  return new URLSearchParams(search).get(PLAN_COPY_PARAM)?.trim() || null
}

export function appPathForActivityTab(tab: ActivityTab): string {
  return tab === "incidents" ? INCIDENTS_PATH : APP_VIEW_PATHS.activity
}

export function appPathForIncident(incidentId: string): string {
  return `${INCIDENTS_PATH}/${encodeURIComponent(incidentId)}`
}

export function appPathForPerson(personId: string): string {
  return `${APP_VIEW_PATHS.people}/${encodeURIComponent(personId)}`
}

export function appPathForSettingsTab(tab: SettingsTab): string {
  return `${APP_VIEW_PATHS.settings}/${tab}`
}

/** Settings → Your account, at Your plan: what the person's plan allows, and how much of it they have. */
export function yourPlanPath(): string {
  return `${appPathForSettingsTab("account")}#your-plan`
}

/** Activity's address: one Incident, the Incidents tab, or History. */
function activityPathForLocation(location: AppLocation): string {
  if (location.incidentId) return appPathForIncident(location.incidentId)
  return appPathForActivityTab(location.activityTab ?? DEFAULT_ACTIVITY_TAB)
}

function rulePath(ruleId: string, preview: boolean | undefined): string {
  return preview ? appPathForRulePreview(ruleId) : appPathForRule(ruleId)
}

/** People's address: one person's page, a Plan's panel, a tab, or Everyone. */
function peoplePathForLocation({ personId, planPanel, peopleTab }: AppLocation): string {
  if (personId) return appPathForPerson(personId)
  if (planPanel) return appPathForPlanPanel(planPanel)
  return appPathForPeopleTab(peopleTab ?? DEFAULT_PEOPLE_TAB)
}

export function appPathForLocation(location: AppLocation): string {
  if (location.ruleId !== null) return rulePath(location.ruleId, location.rulePreview)
  if (location.view === "people") return peoplePathForLocation(location)
  if (location.view === "activity") return activityPathForLocation(location)
  if (location.view === "settings" && location.settingsTab) return appPathForSettingsTab(location.settingsTab)
  return appPathForView(location.view)
}

export function isKnownAppPath(pathname: string): boolean {
  const normalized = normalize(pathname)
  return (
    PATH_VIEWS.has(normalized) ||
    peopleTabFromPath(normalized) !== null ||
    planPanelFromPath(normalized) !== null ||
    normalized === INCIDENTS_PATH ||
    idFromPath(INCIDENT_PATH, normalized) !== null ||
    ruleIdFromPath(normalized) !== null ||
    idFromPath(RULE_PREVIEW_PATH, normalized) !== null ||
    idFromPath(PERSON_PATH, normalized) !== null ||
    settingsTabFromPath(normalized) !== null
  )
}

export function isPlainLeftClick(event: {
  button: number
  metaKey: boolean
  ctrlKey: boolean
  shiftKey: boolean
  altKey: boolean
}): boolean {
  return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey
}
