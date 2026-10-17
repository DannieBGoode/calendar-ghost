import { useState } from "react"

import type { PlanCommands } from "@/lib/use-plans"

/**
 * The one form or confirmation open on the Plans tab: a Plan's edit, the people it is given to, or
 * its removal; or a new Plan, which may start as a copy of another (`copyOf`, its key).
 */
export type PlanWork = { action: "edit" | "assign" | "remove"; key: string } | { action: "new"; copyOf: string | null } | null

/**
 * What the Plans tab has open, and where focus goes as it closes. While a Plan command is on its
 * way, nothing else opens: opening another form forgets the command, and a refusal it met would
 * show nowhere. Opening one forgets the refusals of the last.
 */
export function usePlanWork({ setting, define, change, remove, assign }: PlanCommands) {
  const [work, setWork] = useState<PlanWork>(null)
  // The Plan just added, whose row takes focus once it shows.
  const [added, setAdded] = useState<string | null>(null)
  // New plan takes focus once shown, as after a removal or a new Plan's Cancel.
  const [newFocus, setNewFocus] = useState(false)
  const busy = [setting, define, change, remove, assign].some((command) => command.isPending)

  function open(next: PlanWork) {
    if (busy) return
    define.reset()
    change.reset()
    remove.reset()
    assign.reset()
    setAdded(null)
    setWork(next)
  }

  return {
    work,
    busy,
    added,
    newFocus,
    open,
    /** Closes what is open, as its Cancel or its success does; focus is the caller's to move. */
    close: () => setWork(null),
    /** Closes the new Plan's form; its row takes focus once it shows. */
    closeAdded: (key: string) => {
      setWork(null)
      setAdded(key)
    },
    /** Closes what is open and moves focus to New plan, wherever it shows next. */
    closeToNew: () => {
      setWork(null)
      setNewFocus(true)
    },
    /** New plan took focus. */
    newFocused: () => setNewFocus(false),
  }
}

export type PlanWorkControls = ReturnType<typeof usePlanWork>
