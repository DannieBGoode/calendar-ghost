import { useState } from "react"

import type { PeopleQuery } from "@/lib/api"
import { peopleQueryFromSearch, peopleSearch } from "@/lib/people-query"

/** Whether a change adds a history entry, as a new page does, or replaces the current one. */
type HistoryMode = "push" | "replace"
export type UpdatePeopleQuery = (next: Partial<PeopleQuery>, history: HistoryMode) => void

/**
 * The People page's query lives in the address so reload, Back, and shared links keep it. The
 * page remounts on every arrival, including Back and Forward, so it reads the address only once.
 */
export function usePeopleLocation(): readonly [PeopleQuery, UpdatePeopleQuery] {
  const [query, setQuery] = useState(() => peopleQueryFromSearch(window.location.search))

  function update(next: Partial<PeopleQuery>, history: HistoryMode) {
    const merged = { ...query, ...next }
    const url = `${window.location.pathname}${peopleSearch(merged)}`
    if (history === "push") window.history.pushState(null, "", url)
    else window.history.replaceState(null, "", url)
    setQuery(merged)
  }

  return [query, update] as const
}
