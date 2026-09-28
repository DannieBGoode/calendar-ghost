export type AppView = "overview" | "rules" | "activity" | "settings"
export type AppLocation = { view: AppView; ruleId: string | null }
/**
 * Changes view. A notice is announced on arrival; `createRule` opens the rule builder; `search`
 * carries filters such as `?rule=` into the destination.
 */
export type ViewOptions = { notice?: string; createRule?: boolean; search?: string }
export type ViewChange = (view: AppView, options?: ViewOptions) => void
export type OpenRule = (ruleId: string, options?: ViewOptions) => void

export function activitySearch(ruleId: string): string {
  return `?rule=${encodeURIComponent(ruleId)}`
}

export const APP_VIEW_PATHS: Record<AppView, string> = {
  overview: "/overview",
  rules: "/rules",
  activity: "/activity",
  settings: "/settings",
}

const PATH_VIEWS = new Map(
  Object.entries(APP_VIEW_PATHS).map(([view, path]) => [path, view as AppView]),
)
const RULE_PATH = /^\/rules\/([^/]+)$/

function normalize(pathname: string): string {
  return pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname
}

function ruleIdFromPath(pathname: string): string | null {
  const match = RULE_PATH.exec(pathname)
  if (!match) return null
  try {
    const ruleId = decodeURIComponent(match[1])
    return ruleId.trim() ? ruleId : null
  } catch {
    return null
  }
}

export function appLocationFromPathname(pathname: string): AppLocation {
  const normalized = normalize(pathname)
  const ruleId = ruleIdFromPath(normalized)
  if (ruleId !== null) return { view: "rules", ruleId }
  return { view: PATH_VIEWS.get(normalized) ?? "overview", ruleId: null }
}

export function appViewFromPathname(pathname: string): AppView {
  return appLocationFromPathname(pathname).view
}

export function appPathForView(view: AppView): string {
  return APP_VIEW_PATHS[view]
}

export function appPathForRule(ruleId: string): string {
  return `${APP_VIEW_PATHS.rules}/${encodeURIComponent(ruleId)}`
}

export function appPathForLocation(location: AppLocation): string {
  return location.ruleId === null ? appPathForView(location.view) : appPathForRule(location.ruleId)
}

export function isKnownAppPath(pathname: string): boolean {
  const normalized = normalize(pathname)
  return PATH_VIEWS.has(normalized) || ruleIdFromPath(normalized) !== null
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
