export type AppView = "overview" | "rules" | "activity" | "settings"
/** The Settings tabs, in order; Installation is for Installation Administrators only. */
export const SETTINGS_TABS = ["connections", "account", "installation"] as const
export type SettingsTab = (typeof SETTINGS_TABS)[number]
export const DEFAULT_SETTINGS_TAB: SettingsTab = "connections"
/** Settings without a tab, as the OAuth callback and account links open it, shows Connections. */
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

const APP_VIEW_PATHS: Record<AppView, string> = {
  overview: "/overview",
  rules: "/rules",
  activity: "/activity",
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
