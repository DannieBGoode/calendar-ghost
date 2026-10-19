import { useCallback, useEffect, useRef, useState } from "react"

import { leaveThen } from "@/lib/leave-guard"
import {
  appLocationFromPathname,
  appPathForPeopleTab,
  appPathForPlanPanel,
  planCopyFromSearch,
  type OpenPlan,
  type PlanPanel,
  type PlanPanelTab,
} from "@/lib/navigation"
import type { PlanCommands } from "@/lib/use-plans"

/**
 * Where focus returns once the panel closes: a Plan's name in the catalog, or New plan with null,
 * and what follows once it has, such as saying what a save did, so the result's toast returns
 * focus there too. `scrollY` is where the page was before the panel opened, to return it there
 * first, rather than leave it scrolled as the panel left it.
 */
export type FocusReturn = { plan: string | null; afterwards?: (() => void) | undefined; scrollY?: number | undefined }

function samePanel(a: PlanPanel, b: PlanPanel): boolean {
  return a.plan === b.plan && a.tab === b.tab
}

/** The panel the address names, read once, as People remounts on every arrival, Back and Forward too. */
function panelAtAddress(): PlanPanel | null {
  return appLocationFromPathname(window.location.pathname).planPanel ?? null
}

/**
 * What the Plans tab has open: the side panel beside the catalog, at its own address, with one
 * Plan's Limits or People, or a new Plan, which may start as a copy of another (`copyOf`, its key);
 * and, under a Plan's row, the confirmation of its removal. Opening the panel from the page moves
 * focus to its title; closing it returns to the Plans tab's address, and focus to the Plan's name
 * or New plan. While a Plan command is on its way, nothing opens or closes, so its answer has a
 * place to show. Opening something forgets the refusals of the last. While the open panel has
 * changes not saved, opening, switching, or closing it asks first (`leaveThen`); once they are
 * saved, the panel closes without asking. Closing returns the page to where it was before the
 * panel opened from it. What outlives the Plans tab, such as a toast, opens a panel through
 * `elsewhere` once the tab is gone; arriving so (`arrivalFocus`), the panel the address opens takes
 * focus as from the page, while one opened by its address alone does not.
 */
export function usePlanWork(
  { setting, define, change, remove, assign }: PlanCommands,
  elsewhere: OpenPlan,
  arrivalFocus: boolean,
) {
  const [panel, setPanel] = useState(panelAtAddress)
  const [copyOf, setCopyOf] = useState(() => (panel?.plan === null ? planCopyFromSearch(window.location.search) : null))
  const [removing, setRemoving] = useState<string | null>(null)
  const [titleFocus, setTitleFocus] = useState(arrivalFocus && panel !== null)
  const [focusReturn, setFocusReturn] = useState<FocusReturn | null>(null)
  // Where the page was as the panel opened from it, to return there as it closes.
  const scrolledFrom = useRef<number | undefined>(undefined)
  const busy = [setting, define, change, remove, assign].some((command) => command.isPending)

  function forget() {
    define.reset()
    change.reset()
    remove.reset()
    assign.reset()
  }

  function show(next: PlanPanel, copy: string | null, history: "push" | "replace") {
    forget()
    setRemoving(null)
    const url = appPathForPlanPanel(next, copy)
    if (history === "push") window.history.pushState(null, "", url)
    else window.history.replaceState(null, "", url)
    setPanel(next)
    setCopyOf(copy)
  }

  /**
   * Opens a panel, with focus on its title: a new entry in the history when none is open or it
   * is the same Plan's other tab, in place of the open one otherwise, as Activity's panel does.
   */
  function openPanel(next: PlanPanel, copy: string | null = null) {
    if (busy || (panel !== null && samePanel(panel, next) && copy === copyOf)) return
    leaveThen(() => {
      if (panel === null) scrolledFrom.current = window.scrollY
      show(next, copy, panel === null || panel.plan === next.plan ? "push" : "replace")
      setTitleFocus(true)
    })
  }

  /** Shows the open Plan's other tab, at its own address; focus stays on the tab. */
  function openTab(tab: PlanPanelTab) {
    const plan = panel?.plan ?? null
    if (busy || plan === null || panel?.tab === tab) return
    leaveThen(() => show({ plan, tab }, null, "push"))
  }

  function closePanel() {
    if (busy || panel === null) return
    const { plan } = panel
    leaveThen(() => {
      window.history.pushState(null, "", appPathForPeopleTab("plans"))
      setFocusReturn({ plan, scrollY: scrolledFrom.current })
      scrolledFrom.current = undefined
      setPanel(null)
      setCopyOf(null)
    })
  }

  // The latest `openPanel` while the Plans tab shows, and null once it is gone.
  const opener = useRef<typeof openPanel | null>(null)
  useEffect(() => {
    opener.current = openPanel
    return () => {
      opener.current = null
    }
  })

  return {
    panel,
    copyOf,
    removing,
    busy,
    titleFocus,
    focusReturn,
    openPanel,
    openTab,
    closePanel,
    /**
     * A Plan was saved, or added: its panel closes without asking, as nothing is left to discard,
     * at the Plans tab's address in place of the panel's, so Back never returns to an empty New
     * plan. Focus returns to the Plan's name, then `afterwards` runs.
     */
    closeSaved: (plan: string, afterwards?: () => void) => {
      window.history.replaceState(null, "", appPathForPeopleTab("plans"))
      setFocusReturn({ plan, afterwards, scrollY: scrolledFrom.current })
      scrolledFrom.current = undefined
      setPanel(null)
      setCopyOf(null)
    },
    /**
     * Opens a panel from what may outlive the Plans tab, such as a toast's next step: in place,
     * as from the page, while the tab shows, and through `elsewhere` once it is gone.
     */
    openLater: useCallback((next: PlanPanel) => (opener.current ?? elsewhere)(next), [elsewhere]),
    /** Asks, under the Plan's row, before removing it. */
    openRemoval: (key: string) => {
      if (busy) return
      forget()
      setRemoving(key)
    },
    /** Closes the removal's confirmation; focus is the caller's to move. */
    closeRemoval: () => setRemoving(null),
    /** Closes the removal's confirmation of a Plan now removed, and moves focus to New plan. */
    removed: () => {
      setRemoving(null)
      setFocusReturn({ plan: null })
    },
    /** The panel's title took focus. */
    titleFocused: useCallback(() => setTitleFocus(false), []),
    /** Focus returned where `focusReturn` said. */
    focusReturned: useCallback(() => setFocusReturn(null), []),
  }
}

export type PlanWorkControls = ReturnType<typeof usePlanWork>
