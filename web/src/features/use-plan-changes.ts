import { useState } from "react"

import { useToast } from "@/components/ui/toast-context"
import { useI18n } from "@/i18n/provider"
import type { PlanSummary } from "@/lib/api"
import { restoredResult, undoMoves } from "@/lib/plan-assignment"
import { changedResult, type PlanPerson } from "@/lib/plan-change"
import { useGivePlans } from "@/lib/use-people"

/** One change from a Change plan chooser. */
type PlanChangeRequest = {
  /** The chooser that made it, whose refusal it then is. */
  source: string
  people: readonly PlanPerson[]
  /** What Save sends: a Plan's key, or null for the default or no Plan. */
  plan: string | null
  /** The Plan chosen, which the result names; null for no Plan. */
  chosen: PlanSummary | null
  /** Once it is made: the chooser closes and focus moves, then `show` says what it did. */
  done: (show: () => void) => void
}

/** Changes people's Plans from Change plan, and what the last change and Undo are doing. */
export type PlanChanges = {
  change: (request: PlanChangeRequest) => void
  /** A change is on its way. */
  pending: boolean
  /** Why the last change from this chooser was refused; null without one. */
  refusalFor: (source: string) => Error | null
  /** Puts the last refusal away, as a new choice or closing the chooser does. */
  forget: () => void
  /** Why the last Undo could not be done, until the next change. */
  undoRefusal: Error | null
}

/**
 * Changes people's Plans from Change plan, for one person or several, and says what each change
 * did in a toast with Undo, which gives each person back the Plan they had and says so. It belongs
 * to what outlasts the chooser, such as the list in Everyone or a person's Plan card: a change can
 * leave nobody in a narrowed list, and the chooser goes with them, while the toast and Undo still
 * have to answer.
 */
export function usePlanChanges(): PlanChanges {
  const i18n = useI18n()
  const toasts = useToast()
  const give = useGivePlans()
  const undo = useGivePlans()
  const [source, setSource] = useState<string | null>(null)

  function change({ source: from, people, plan, chosen, done }: PlanChangeRequest) {
    if (give.isPending) return
    setSource(from)
    undo.reset()
    give.mutate([{ plan, userIds: people.map((person) => person.id) }], {
      onSuccess: ([answer]) =>
        done(() =>
          toasts.show({
            message: changedResult(i18n, people, chosen),
            action: answer && {
              label: i18n.t("common.toast.undo"),
              onSelect: () =>
                undo.mutate(undoMoves(answer), { onSuccess: () => toasts.show({ message: restoredResult(i18n, answer) }) }),
            },
          }),
        ),
    })
  }

  return {
    change,
    pending: give.isPending,
    refusalFor: (from) => (from === source ? give.error : null),
    forget: () => give.reset(),
    undoRefusal: undo.error,
  }
}
