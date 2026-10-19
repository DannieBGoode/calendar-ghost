import { useState } from "react"

const NOTHING: ReadonlySet<string> = new Set()

/**
 * Which rows of a list are selected, by id, for an action on several at once. The selection
 * belongs to `scope`, such as the list's search, filters, sort, and page: once the scope changes,
 * nothing is selected, so a selection never holds rows no longer shown.
 */
export function useRowSelection(scope: string) {
  const [selection, setSelection] = useState<{ scope: string; ids: ReadonlySet<string> }>({ scope, ids: NOTHING })
  const ids = selection.scope === scope ? selection.ids : NOTHING
  const keep = (next: ReadonlySet<string>) => setSelection({ scope, ids: next })
  return {
    ids,
    /** Selects one row, or leaves it out. */
    toggle: (id: string, selected: boolean) => {
      const next = new Set(ids)
      if (selected) next.add(id)
      else next.delete(id)
      keep(next)
    },
    /** Selects every row given, or none. */
    setAll: (all: readonly string[], selected: boolean) => keep(selected ? new Set(all) : NOTHING),
    clear: () => keep(NOTHING),
  }
}

export type RowSelection = ReturnType<typeof useRowSelection>
