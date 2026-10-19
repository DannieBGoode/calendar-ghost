import { useState } from "react"

import { useToast } from "@/components/ui/toast-context"
import type { PlanChooserProps } from "@/features/plan-change"
import { answerUndo } from "@/features/undo"
import { useI18n } from "@/i18n/provider"
import { restoredResult, undoMoves } from "@/lib/plan-assignment"
import { changedResult, type PlanPerson } from "@/lib/plan-change"
import { useGivePlans } from "@/lib/use-people"

/** Once a change is made: the chooser closes and focus moves, then `show` says what it did. */
type Done = (show: () => void) => void

/** What one Change plan chooser takes: what it waits on, its own refusal, and its Save. */
type ChooserBinding = Pick<PlanChooserProps, "pending" | "refusal" | "onChoose" | "onSave">

/** Changes people's Plans from Change plan, and what the last change and Undo are doing. */
export type PlanChanges = {
  /** The chooser `source` that changes `people`'s Plan; its refusal is its own. */
  chooser: (source: string, people: readonly PlanPerson[], done: Done) => ChooserBinding
  /** A change is on its way. */
  pending: boolean
  /** Puts the last refusal away, as a new choice or closing the chooser does. */
  forget: () => void
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

  function chooser(from: string, people: readonly PlanPerson[], done: Done): ChooserBinding {
    const refusal = from === source ? give.error : null
    return {
      pending: give.isPending,
      refusal,
      onChoose: () => refusal && give.reset(),
      onSave: (plan, chosen) => {
        if (give.isPending) return
        setSource(from)
        give.mutate([{ plan, userIds: people.map((person) => person.id) }], {
          onSuccess: ([answer]) =>
            done(() =>
              toasts.show({
                message: changedResult(i18n, people, chosen),
                action: answer && {
                  label: i18n.t("common.toast.undo"),
                  onSelect: () =>
                    answerUndo(toasts, i18n, undo.mutateAsync(undoMoves(answer)), () => ({ message: restoredResult(i18n, answer) })),
                },
              }),
            ),
        })
      },
    }
  }

  return { chooser, pending: give.isPending, forget: () => give.reset() }
}
