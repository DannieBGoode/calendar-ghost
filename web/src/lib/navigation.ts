export type AppView = "overview" | "rules" | "activity" | "people" | "settings"
/** The Settings tabs, in order; Administration is for Installation Administrators only. */
export const SETTINGS_TABS = ["account", "connections", "administration"] as const
export type SettingsTab = (typeof SETTINGS_TABS)[number]
/** The tab Settings opens at unless Google's return or an account link calls for Connections. */
export const DEFAULT_SETTINGS_TAB: SettingsTab = "account"
/** What Google's return, or a link to one Connected Account, carries in the address. */
export const SETTINGS_ARRIVAL_PARAMS = ["google", "account", "resumed"] as const

/**
 * The tab Settings without one shows: Connections when Google returned or an account is named,
 * as the OAuth callback and older links open it, and Your account otherwise.
 */
export function defaultSettingsTab(search: string): SettingsTab {
  const params = new URLSearchParams(search)
  return SETTINGS_ARRIVAL_PARAMS.some((name) => params.has(name)) ? "connections" : DEFAULT_SETTINGS_TAB
}

export type AppLocation = { view: AppView; ruleId: string | null; settingsTab?: SettingsTab }
/**
 * Changes view. A notice is announced on arrival; `createRule` opens the rule builder; `search`
 * carries filters such as `?rule=` into the destination.
 */
export type ViewOptions = {
  notice?: string
  /** An attention notice stays until dismissed and offers a way to review what happened. */
  noticeTone?: "attention" | undefined
  createRule?: boolean
  search?: string
  /** The Settings tab to open, such as Connections for a link about Google accounts. */
  settingsTab?: SettingsTab
}
export type ViewChange = (view: AppView, options?: ViewOptions) => void
export type OpenRule = (ruleId: string, options?: ViewOptions) => void
export type OpenSettingsTab = (tab: SettingsTab) => void

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
const SETTINGS_TAB_PATH = /^\/settings\/([^/]+)$/

function normalize(pathname: string): string {
  return pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname
}

function ruleIdFromPath(pathname: string): string | null {
  const encoded = RULE_PATH.exec(pathname)?.[1]
  if (encoded === undefined) return null
  try {
    const ruleId = decodeURIComponent(encoded)
    return ruleId.trim() ? ruleId : null
  } catch {
    return null
  }
}

function settingsTabFromPath(pathname: string): SettingsTab | null {
  const segment = SETTINGS_TAB_PATH.exec(pathname)?.[1]
  return SETTINGS_TABS.find((tab) => tab === segment) ?? null
}

export function appLocationFromPathname(pathname: string): AppLocation {
  const normalized = normalize(pathname)
  const ruleId = ruleIdFromPath(normalized)
  if (ruleId !== null) return { view: "rules", ruleId }
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

export function appPathForSettingsTab(tab: SettingsTab): string {
  return `${APP_VIEW_PATHS.settings}/${tab}`
}

export function appPathForLocation(location: AppLocation): string {
  if (location.ruleId !== null) return appPathForRule(location.ruleId)
  if (location.view === "settings" && location.settingsTab) return appPathForSettingsTab(location.settingsTab)
  return appPathForView(location.view)
}

export function isKnownAppPath(pathname: string): boolean {
  const normalized = normalize(pathname)
  return PATH_VIEWS.has(normalized) || ruleIdFromPath(normalized) !== null || settingsTabFromPath(normalized) !== null
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
