import { useCallback, useState } from "react"

import { leaveThen } from "@/lib/leave-guard"
import {
  appLocationFromPathname,
  appPathForPeopleTab,
  appPathForPlanPanel,
  planCopyFromSearch,
  type PlanPanel,
  type PlanPanelTab,
} from "@/lib/navigation"
import type { PlanCommands } from "@/lib/use-plans"

/** Where focus returns once the panel closes: a Plan's name in the catalog, or New plan with null. */
export type FocusReturn = { plan: string | null }

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
 * changes not saved, opening, switching, or closing it asks first (`leaveThen`).
 */
export function usePlanWork({ setting, define, change, remove, assign }: PlanCommands) {
  const [panel, setPanel] = useState(panelAtAddress)
  const [copyOf, setCopyOf] = useState(() => (panel?.plan === null ? planCopyFromSearch(window.location.search) : null))
  const [removing, setRemoving] = useState<string | null>(null)
  const [titleFocus, setTitleFocus] = useState(false)
  const [focusReturn, setFocusReturn] = useState<FocusReturn | null>(null)
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
      setFocusReturn({ plan })
      setPanel(null)
      setCopyOf(null)
    })
  }

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
    /** A new Plan was saved: its panel moves to the Plan's own address, with focus on its title. */
    showAdded: (key: string) => {
      const next: PlanPanel = { plan: key, tab: "limits" }
      window.history.replaceState(null, "", appPathForPlanPanel(next))
      setPanel(next)
      setCopyOf(null)
      setTitleFocus(true)
    },
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
