import { useToast } from "@/components/ui/toast-context"
import { useI18n } from "@/i18n/provider"
import type { PlanAssignments } from "@/lib/api"
import { restoredResult, undoMoves } from "@/lib/plan-assignment"
import { useGivePlans } from "@/lib/use-people"

/** Says what a change of several people's plans did, with Undo when the answer names who moved. */
export type ShowPlanChange = (message: string, answer: PlanAssignments | undefined) => void

/**
 * The toast that answers a change of several people's plans from Everyone, with Undo, which gives
 * each person back the Plan they had and says so. It belongs to the list, not to the bar above
 * it: a change can leave nobody in a narrowed list, and the bar goes with them, while Undo still
 * has to say what it did, or why it could not. `refusal` is why the last Undo could not, until the
 * next change.
 */
export function usePlanChangeToast(): { show: ShowPlanChange; refusal: Error | null } {
  const i18n = useI18n()
  const toasts = useToast()
  const undo = useGivePlans()
  const show: ShowPlanChange = (message, answer) => {
    undo.reset()
    toasts.show({
      message,
      action: answer && {
        label: i18n.t("common.toast.undo"),
        onSelect: () =>
          undo.mutate(undoMoves(answer), { onSuccess: () => toasts.show({ message: restoredResult(i18n, answer) }) }),
      },
    })
  }
  return { show, refusal: undo.error }
}
