import { useCallback, useEffect, useState } from "react"

/**
 * A form with changes not saved, which asks before the page leaves it: `ask` shows its question
 * and calls `leave` once the person discards the changes. `address` is the form's own, where Back
 * and Forward return while it asks.
 */
type LeaveGuard = { address: string; ask: (leave: () => void) => void }

/** The one form guarding the page now, if any. */
let guard: LeaveGuard | null = null

/**
 * Leaves at once, or, while a form has changes not saved, once the person discards them. Every
 * way the app leaves a page, or a panel within one, goes through here.
 */
export function leaveThen(leave: () => void): void {
  if (guard) guard.ask(leave)
  else leave()
}

/**
 * Back or Forward has just left a form with changes not saved: returns to the form's address and
 * asks, going where the browser went once the changes are discarded. Says whether it held the page.
 */
export function holdHistory(): boolean {
  const held = guard
  if (!held) return false
  window.history.pushState(null, "", held.address)
  held.ask(() => window.history.back())
  return true
}

/**
 * While `unsaved`, asks through `ask`, which must keep its identity, before the page leaves the
 * form, and has the browser ask before the tab closes or reloads.
 */
function useLeaveGuard(unsaved: boolean, ask: (leave: () => void) => void) {
  useEffect(() => {
    if (!unsaved) return
    const own: LeaveGuard = { address: `${window.location.pathname}${window.location.search}`, ask }
    guard = own
    const unload = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener("beforeunload", unload)
    return () => {
      if (guard === own) guard = null
      window.removeEventListener("beforeunload", unload)
    }
  }, [unsaved, ask])
}

/** The question a form shows before the page leaves it, and the element focus was on as it asked. */
export type LeaveQuestion = { leave: () => void; from: Element | null }

/**
 * Guards the page while `unsaved` and holds the question the form shows: `asking` until the
 * person answers it, or until nothing is left to lose, so it never comes back by itself with later
 * changes; `keep` puts it away, keeping the changes; `discard` lets the page leave as it was about
 * to. Focus is the form's to move.
 */
export function useLeaveQuestion(unsaved: boolean) {
  const [asking, setAsking] = useState<LeaveQuestion | null>(null)
  if (!unsaved && asking !== null) setAsking(null)
  const ask = useCallback((leave: () => void) => setAsking({ leave, from: document.activeElement }), [])
  useLeaveGuard(unsaved, ask)
  return {
    asking,
    keep: () => setAsking(null),
    discard: () => {
      setAsking(null)
      guard = null
      asking?.leave()
    },
  }
}
