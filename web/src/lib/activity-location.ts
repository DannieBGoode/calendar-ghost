import type { ActivityCategory } from "@/lib/api"

/** "" hides no-change checks; "all" includes them. */
export type ActivityShow = "" | "all" | ActivityCategory
export type ActivityLocationState = {
  ruleId: string
  show: ActivityShow
  entryId: number | null
  /** Text searched for in recorded event titles. */
  query?: string
}

const SHOW_VALUES = new Set<string>(["all", "changed", "skipped", "blocked", "unchanged"])

export function activityStateFromSearch(search: string): ActivityLocationState {
  const params = new URLSearchParams(search)
  // Links from earlier releases name the outcome with `category`.
  const show = params.get("show") ?? params.get("category") ?? ""
  const entry = Number(params.get("entry"))
  return {
    ruleId: params.get("rule") ?? "",
    show: SHOW_VALUES.has(show) ? (show as ActivityShow) : "",
    entryId: Number.isInteger(entry) && entry > 0 ? entry : null,
    query: params.get("q")?.trim() ?? "",
  }
}

export function activitySearch(state: ActivityLocationState, options: { preview?: boolean } = {}): string {
  const params = new URLSearchParams()
  if (options.preview) params.set("preview", "1")
  if (state.ruleId) params.set("rule", state.ruleId)
  if (state.show) params.set("show", state.show)
  if (state.query?.trim()) params.set("q", state.query.trim())
  if (state.entryId !== null) params.set("entry", String(state.entryId))
  const search = params.toString()
  return search ? `?${search}` : ""
}
